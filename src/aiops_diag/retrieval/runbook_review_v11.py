"""Prepare and score a blinded, event-level runbook relevance review."""

import json
import os
import shutil
import uuid
from pathlib import Path

from aiops_diag.agent.config import load as load_agent
from aiops_diag.data.common import digest, save
from aiops_diag.retrieval.release import FrozenRetriever


def _rows(path):
    return [json.loads(line) for line in Path(path).read_text(
        encoding="utf-8").splitlines() if line.strip()]


def _write_rows(path, rows):
    Path(path).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n"
                             for row in rows), encoding="utf-8")


def _sealed_cases(fixture_dir):
    fixture_dir = Path(fixture_dir)
    manifest_path, cases_path = fixture_dir / "manifest.json", fixture_dir / "cases.jsonl"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("status") != "REPORT_STABILITY_FIXTURES_ONLY"
            or manifest.get("cases_sha256") != digest(cases_path)):
        raise ValueError("Report fixtures are not sealed")
    cases = _rows(cases_path)
    if len(cases) != manifest["count"] or len({c["case_id"] for c in cases}) != len(cases):
        raise ValueError("Report fixture count or IDs changed")
    return manifest, cases, digest(manifest_path), digest(cases_path)


def _log_sample(case):
    logs = [e for e in case["evidence"] if e["kind"] == "log"]
    ordered = sorted(logs, key=lambda e: (e.get("level") not in {"WARN", "ERROR"},
                                          e.get("observed_at", "")))
    result, seen = [], set()
    for row in ordered:
        excerpt = row["excerpt_redacted"][:300]
        if excerpt in seen:
            continue
        seen.add(excerpt)
        result.append({"observed_at": row.get("observed_at"),
                       "component": row.get("component"),
                       "level": row.get("level"), "excerpt_redacted": excerpt})
        if len(result) == 8:
            break
    return result


def build(agent_config, fixture_dir, output_dir):
    """Write a shareable blank packet and a separate, private return-map key."""
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError("Review directory already exists")
    manifest, cases, manifest_hash, cases_hash = _sealed_cases(fixture_dir)
    cfg = load_agent(agent_config)
    frozen = FrozenRetriever(cfg["rag"]["retrieval"])
    if manifest["kb_release_id"] != frozen.manifest["kb_release_id"]:
        raise ValueError("Fixture knowledge release changed")
    packet, key = [], []
    for case in cases:
        components = sorted({e.get("component") for e in case["evidence"]
                             if e["kind"] == "log" and e.get("component")})
        query = "HDFS异常事件只读排查 " + " ".join(components[:5])
        old = frozen.search(query, mode="frozen",
                            top_k=cfg["tools"]["runbook_top_k"],
                            component=components[0] if len(components) == 1 else None)
        baseline_ids = [e["chunk_id"] for e in old["items"]]
        candidate_ids = [e["evidence_id"] for e in case["evidence"]
                         if e["kind"] == "doc"]
        if len(candidate_ids) != case["returned_doc_count"]:
            raise ValueError("Candidate fixture document count changed")
        documents = []
        for chunk_id in sorted(set(baseline_ids + candidate_ids)):
            row = frozen.chunk(chunk_id)
            if row is None:
                raise ValueError(f"Unknown knowledge chunk: {chunk_id}")
            documents.append({"doc_id": chunk_id, "title": row["title"],
                              "section_path": row["section_path"],
                              "source_url": row["source_url"],
                              "source_version": row["source_version"],
                              "text": row["text"]})
        packet.append({"case_id": case["case_id"],
                       "time_window": {k: case["event"].get(k) for k in
                                       ("start_time", "end_time")},
                       "log_count": case["log_count"],
                       "log_sample": _log_sample(case),
                       "documents": documents,
                       "review_relevance": {d["doc_id"]: None for d in documents},
                       "reviewer_id": None, "review_notes": None})
        key.append({"case_id": case["case_id"],
                    "baseline_doc_ids": baseline_ids,
                    "candidate_doc_ids": candidate_ids})
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = output_dir.parent / f".{output_dir.name}.{uuid.uuid4().hex}.partial"
    try:
        staging.mkdir()
        _write_rows(staging / "packet.jsonl", packet)
        _write_rows(staging / "return_map.private.jsonl", key)
        result = {"schema_version": 1, "status": "AWAITING_INDEPENDENT_RELEVANCE_REVIEW",
                  "fixture_manifest_sha256": manifest_hash,
                  "fixture_cases_sha256": cases_hash,
                  "candidate_release_id": manifest["candidate_release_id"],
                  "kb_release_id": manifest["kb_release_id"],
                  "case_count": len(packet),
                  "packet_sha256": digest(staging / "packet.jsonl"),
                  "return_map_sha256": digest(staging / "return_map.private.jsonl"),
                  "limitation": "Pooled documents only; no root-cause labels or exhaustive relevance judgments."}
        save(staging / "manifest.json", result)
        os.replace(staging, output_dir)
        return result
    finally:
        if staging.exists() and staging.resolve().parent == output_dir.parent.resolve():
            shutil.rmtree(staging)


def evaluate(review_dir, submission_path):
    """Validate completed labels, then compare return relevance within the pooled docs."""
    review_dir = Path(review_dir)
    manifest = json.loads((review_dir / "manifest.json").read_text(encoding="utf-8"))
    packet_path, key_path = review_dir / "packet.jsonl", review_dir / "return_map.private.jsonl"
    if (manifest.get("status") != "AWAITING_INDEPENDENT_RELEVANCE_REVIEW"
            or digest(packet_path) != manifest["packet_sha256"]
            or digest(key_path) != manifest["return_map_sha256"]):
        raise ValueError("Review packet or return map changed")
    packet, key, labels = _rows(packet_path), _rows(key_path), _rows(submission_path)
    if len(packet) != manifest["case_count"] or len(packet) != len(key) or len(packet) != len(labels):
        raise ValueError("Review submission count changed")
    counts = {name: 0 for name in ("baseline_returned", "candidate_returned",
                                  "baseline_any_relevant", "candidate_any_relevant",
                                  "baseline_only_relevant", "candidate_only_relevant",
                                  "both_relevant", "neither_relevant")}
    reviewers = set()
    for blank, mapping, reviewed in zip(packet, key, labels):
        fixed = set(blank) - {"review_relevance", "reviewer_id", "review_notes"}
        if (set(reviewed) != set(blank) or any(reviewed[k] != blank[k] for k in fixed)
                or mapping["case_id"] != blank["case_id"]
                or not isinstance(reviewed["reviewer_id"], str)
                or not reviewed["reviewer_id"].strip()
                or reviewed["reviewer_id"].strip().casefold() in {"project", "codex"}
                or not isinstance(reviewed["review_notes"], str)
                or not reviewed["review_notes"].strip()):
            raise ValueError("Review submission is incomplete or changed")
        scores = reviewed["review_relevance"]
        ids = {d["doc_id"] for d in blank["documents"]}
        if (not isinstance(scores, dict) or set(scores) != ids
                or any(type(v) is not int or v not in {0, 1, 2} for v in scores.values())
                or not set(mapping["baseline_doc_ids"] + mapping["candidate_doc_ids"]) <= ids):
            raise ValueError("Relevance labels or return map are invalid")
        reviewers.add(reviewed["reviewer_id"].strip())
        old, new = mapping["baseline_doc_ids"], mapping["candidate_doc_ids"]
        old_hit, new_hit = any(scores[d] >= 1 for d in old), any(scores[d] >= 1 for d in new)
        counts["baseline_returned"] += bool(old)
        counts["candidate_returned"] += bool(new)
        counts["baseline_any_relevant"] += old_hit
        counts["candidate_any_relevant"] += new_hit
        counts[("both_relevant" if old_hit and new_hit else
                "baseline_only_relevant" if old_hit else
                "candidate_only_relevant" if new_hit else "neither_relevant")] += 1
    return {"schema_version": 1, "status": "STRUCTURALLY_REVIEWED_NOT_ADJUDICATED",
            "packet_manifest_sha256": digest(review_dir / "manifest.json"),
            "submission_sha256": digest(submission_path),
            "case_count": len(packet), "reviewers": sorted(reviewers), **counts,
            "limitation": "Labels are pooled document relevance, not verified reviewer identity, exhaustive relevance, or root-cause accuracy."}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("build")
    for name in ("agent_config", "fixture_dir", "output_dir"):
        make.add_argument(name, type=Path)
    score = sub.add_parser("evaluate")
    for name in ("review_dir", "submission", "output"):
        score.add_argument(name, type=Path)
    args = parser.parse_args()
    if args.command == "build":
        result = build(args.agent_config, args.fixture_dir, args.output_dir)
    else:
        if args.output.exists():
            raise FileExistsError("Review result already exists")
        result = evaluate(args.review_dir, args.submission)
        save(args.output, result)
    print(json.dumps(result, ensure_ascii=False))
