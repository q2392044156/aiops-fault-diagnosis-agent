"""复核 runbook 的返回覆盖：生成盲评包、给出覆盖统计，并在评分后核对返回相关性。"""

import json
import os
import shutil
import uuid
from pathlib import Path

from aiops_diag.common import digest, save
from online.diagnosis.settings import load as load_agent
from online.knowledge.jsonl import read_rows, write_rows
from online.knowledge.release import FrozenRetriever


def _sealed_cases(fixture_dir):
    """读出已密封的用例目录；清单或用例被改动就拒绝复核。"""
    fixture_dir = Path(fixture_dir)
    manifest_path, cases_path = fixture_dir / "manifest.json", fixture_dir / "cases.jsonl"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("status") != "REPORT_STABILITY_FIXTURES_ONLY"
            or manifest.get("cases_sha256") != digest(cases_path)):
        raise ValueError("Report fixtures are not sealed")
    cases = read_rows(cases_path)
    if len(cases) != manifest["count"] or len({c["case_id"] for c in cases}) != len(cases):
        raise ValueError("Report fixture count or IDs changed")
    return manifest, cases, digest(manifest_path), digest(cases_path)


def _components(case):
    """用例日志行涉及的产品组件，去重后按字典序给出检索线索。"""
    return sorted({row.get("component") for row in case["evidence"]
                   if row["kind"] == "log" and row.get("component")})


def _runbook_query(case):
    """把组件名拼成只读排查用的 runbook 查询，整条用例共用同一条查询。"""
    components = _components(case)
    return "HDFS异常事件只读排查 " + " ".join(components[:5]), components


def _frozen(agent_config, manifest):
    """按服务配置加载冻结知识库，并要求与用例清单是同一份发布。"""
    cfg = load_agent(agent_config)
    frozen = FrozenRetriever(cfg["rag"]["retrieval"])
    if manifest["kb_release_id"] != frozen.manifest["kb_release_id"]:
        raise ValueError("Fixture knowledge release changed")
    return cfg, frozen


def _baseline(frozen, cfg, case):
    """基线返回：v1.0 冻结检索在同一条查询上的结果。"""
    query, components = _runbook_query(case)
    return frozen.search(query, mode="frozen", top_k=cfg["tools"]["runbook_top_k"],
                         component=components[0] if len(components) == 1 else None)


def _log_sample(case):
    """盲评包里的日志节选：优先告警级别，按时间排序，去重后最多八条。"""
    logs = [row for row in case["evidence"] if row["kind"] == "log"]
    ordered = sorted(logs, key=lambda row: (row.get("level") not in {"WARN", "ERROR"},
                                            row.get("observed_at", "")))
    sample, seen = [], set()
    for row in ordered:
        excerpt = row["excerpt_redacted"][:300]
        if excerpt in seen:
            continue
        seen.add(excerpt)
        sample.append({"observed_at": row.get("observed_at"),
                       "component": row.get("component"),
                       "level": row.get("level"), "excerpt_redacted": excerpt})
        if len(sample) == 8:
            break
    return sample


def coverage(agent_config, fixture_dir):
    """统计基线与候选各自返回了 runbook 文档的用例数；这只说明覆盖，不说明相关性。"""
    manifest, cases, manifest_hash, cases_hash = _sealed_cases(fixture_dir)
    cfg, frozen = _frozen(agent_config, manifest)
    rows = []
    for case in cases:
        components = _components(case)
        old = _baseline(frozen, cfg, case)
        rows.append({"case_id": case["case_id"],
                     "baseline_returned": old["status"] == "evidence_found",
                     "candidate_returned": case["returned_doc_count"] > 0,
                     "has_log": any(row["kind"] == "log" for row in case["evidence"]),
                     "component_count": len(components)})
    return {"schema_version": 1, "status": "COVERAGE_ONLY_NO_RELEVANCE_LABELS",
            "fixture_manifest_sha256": manifest_hash,
            "fixture_cases_sha256": cases_hash,
            "candidate_release_id": manifest["candidate_release_id"],
            "kb_release_id": manifest["kb_release_id"],
            "baseline_returned": sum(row["baseline_returned"] for row in rows),
            "candidate_returned": sum(row["candidate_returned"] for row in rows),
            "query_count": len(rows), "cases": rows,
            "limitation": "No relevance labels or true root-cause labels; return coverage is not accuracy."}


def build(agent_config, fixture_dir, output_dir):
    """写出可外发的空白盲评包，返回映射单独落成私有文件。"""
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError("Review directory already exists")
    manifest, cases, manifest_hash, cases_hash = _sealed_cases(fixture_dir)
    cfg, frozen = _frozen(agent_config, manifest)
    packet, mapping_rows = [], []
    for case in cases:
        baseline_ids = [row["chunk_id"] for row in _baseline(frozen, cfg, case)["items"]]
        candidate_ids = [row["evidence_id"] for row in case["evidence"]
                         if row["kind"] == "doc"]
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
                       "time_window": {name: case["event"].get(name) for name in
                                       ("start_time", "end_time")},
                       "log_count": case["log_count"],
                       "log_sample": _log_sample(case),
                       "documents": documents,
                       "review_relevance": {doc["doc_id"]: None for doc in documents},
                       "reviewer_id": None, "review_notes": None})
        mapping_rows.append({"case_id": case["case_id"],
                             "baseline_doc_ids": baseline_ids,
                             "candidate_doc_ids": candidate_ids})
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = output_dir.parent / f".{output_dir.name}.{uuid.uuid4().hex}.partial"
    try:
        staging.mkdir()
        write_rows(staging / "packet.jsonl", packet)
        write_rows(staging / "return_map.private.jsonl", mapping_rows)
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
    """校验回收的标注，再在候选文档池内比较基线与候选的返回相关性。"""
    review_dir = Path(review_dir)
    manifest = json.loads((review_dir / "manifest.json").read_text(encoding="utf-8"))
    packet_path = review_dir / "packet.jsonl"
    key_path = review_dir / "return_map.private.jsonl"
    if (manifest.get("status") != "AWAITING_INDEPENDENT_RELEVANCE_REVIEW"
            or digest(packet_path) != manifest["packet_sha256"]
            or digest(key_path) != manifest["return_map_sha256"]):
        raise ValueError("Review packet or return map changed")
    packet = read_rows(packet_path)
    mapping = read_rows(key_path)
    labels = read_rows(submission_path)
    if len(packet) != manifest["case_count"] or len(packet) != len(mapping) or len(packet) != len(labels):
        raise ValueError("Review submission count changed")
    counts = dict.fromkeys(("baseline_returned", "candidate_returned", "baseline_any_relevant", "candidate_any_relevant", "baseline_only_relevant", "candidate_only_relevant", "both_relevant", "neither_relevant"), 0)
    reviewers = set()
    for blank, positions, reviewed in zip(packet, mapping, labels, strict=False):
        fixed = set(blank) - {"review_relevance", "reviewer_id", "review_notes"}
        if (set(reviewed) != set(blank) or any(reviewed[name] != blank[name] for name in fixed)
                or positions["case_id"] != blank["case_id"]
                or not isinstance(reviewed["reviewer_id"], str)
                or not reviewed["reviewer_id"].strip()
                or reviewed["reviewer_id"].strip().casefold() in {"project", "codex"}
                or not isinstance(reviewed["review_notes"], str)
                or not reviewed["review_notes"].strip()):
            raise ValueError("Review submission is incomplete or changed")
        scores = reviewed["review_relevance"]
        ids = {doc["doc_id"] for doc in blank["documents"]}
        if (not isinstance(scores, dict) or set(scores) != ids
                or any(type(value) is not int or value not in {0, 1, 2}
                       for value in scores.values())
                or not set(positions["baseline_doc_ids"]
                           + positions["candidate_doc_ids"]) <= ids):
            raise ValueError("Relevance labels or return map are invalid")
        reviewers.add(reviewed["reviewer_id"].strip())
        old, new = positions["baseline_doc_ids"], positions["candidate_doc_ids"]
        old_hit, new_hit = any(scores[doc] >= 1 for doc in old), any(scores[doc] >= 1 for doc in new)
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
    summary = sub.add_parser("coverage")
    for name in ("agent_config", "fixture_dir", "output"):
        summary.add_argument(name, type=Path)
    packet = sub.add_parser("build")
    for name in ("agent_config", "fixture_dir", "output_dir"):
        packet.add_argument(name, type=Path)
    score = sub.add_parser("evaluate")
    for name in ("review_dir", "submission", "output"):
        score.add_argument(name, type=Path)
    args = parser.parse_args()
    if args.command == "coverage":
        if args.output.exists():
            raise FileExistsError("Coverage report already exists")
        result = coverage(args.agent_config, args.fixture_dir)
        save(args.output, result)
        print(json.dumps({name: result[name] for name in (
            "status", "query_count", "baseline_returned", "candidate_returned")},
            ensure_ascii=False))
    elif args.command == "build":
        result = build(args.agent_config, args.fixture_dir, args.output_dir)
        print(json.dumps(result, ensure_ascii=False))
    else:
        if args.output.exists():
            raise FileExistsError("Review result already exists")
        result = evaluate(args.review_dir, args.submission)
        save(args.output, result)
        print(json.dumps(result, ensure_ascii=False))
