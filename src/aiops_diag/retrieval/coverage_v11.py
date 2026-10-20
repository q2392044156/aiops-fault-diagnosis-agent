"""Compare Agent runbook return coverage; this is not a relevance evaluation."""

import json
from pathlib import Path

from aiops_diag.agent.config import load as load_agent
from aiops_diag.data.common import digest, save
from aiops_diag.retrieval.release import FrozenRetriever


def compare(agent_config, fixture_dir):
    fixture_dir = Path(fixture_dir)
    manifest_path, cases_path = fixture_dir / "manifest.json", fixture_dir / "cases.jsonl"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("status") != "REPORT_STABILITY_FIXTURES_ONLY"
            or manifest.get("cases_sha256") != digest(cases_path)):
        raise ValueError("Report fixtures are not sealed")
    cfg = load_agent(agent_config)
    frozen = FrozenRetriever(cfg["rag"]["retrieval"])
    if manifest["kb_release_id"] != frozen.manifest["kb_release_id"]:
        raise ValueError("Fixture knowledge release changed")
    cases = [json.loads(line) for line in cases_path.read_text(
        encoding="utf-8").splitlines() if line.strip()]
    if len(cases) != manifest["count"]:
        raise ValueError("Report fixture count changed")
    rows = []
    for case in cases:
        components = sorted({row.get("component") for row in case["evidence"]
                             if row["kind"] == "log" and row.get("component")})
        query = "HDFS异常事件只读排查 " + " ".join(components[:5])
        legacy = frozen.search(query, mode="frozen",
                               top_k=cfg["tools"]["runbook_top_k"],
                               component=components[0] if len(components) == 1 else None)
        rows.append({"case_id": case["case_id"],
                     "baseline_returned": legacy["status"] == "evidence_found",
                     "candidate_returned": case["returned_doc_count"] > 0,
                     "has_log": any(row["kind"] == "log" for row in case["evidence"]),
                     "component_count": len(components)})
    return {"schema_version": 1, "status": "COVERAGE_ONLY_NO_RELEVANCE_LABELS",
            "fixture_manifest_sha256": digest(manifest_path),
            "fixture_cases_sha256": digest(cases_path),
            "candidate_release_id": manifest["candidate_release_id"],
            "kb_release_id": manifest["kb_release_id"],
            "baseline_returned": sum(row["baseline_returned"] for row in rows),
            "candidate_returned": sum(row["candidate_returned"] for row in rows),
            "query_count": len(rows), "cases": rows,
            "limitation": "No relevance labels or true root-cause labels; return coverage is not accuracy."}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agent_config", type=Path)
    parser.add_argument("fixture_dir", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Coverage report already exists")
    value = compare(args.agent_config, args.fixture_dir)
    save(args.output, value)
    print(json.dumps({key: value[key] for key in (
        "status", "query_count", "baseline_returned", "candidate_returned")},
        ensure_ascii=False))
