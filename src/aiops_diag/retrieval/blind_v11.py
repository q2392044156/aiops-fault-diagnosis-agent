"""Run an immutable, release-bound v1.1 retrieval acceptance comparison."""

import json
import os
import shutil
import statistics
import uuid
from collections import defaultdict
from pathlib import Path

from aiops_diag.agent.config import load as load_agent
from aiops_diag.agent_v11.release import verify as verify_candidate
from aiops_diag.data.common import digest, save
from aiops_diag.retrieval.evaluation import evaluate
from aiops_diag.retrieval.gate_v11 import CandidateRetriever
from aiops_diag.retrieval.protocol_v11 import validate_protocol
from aiops_diag.retrieval.release import FrozenRetriever


def _read_sealed_test(protocol_path):
    protocol_path = Path(protocol_path).resolve()
    directory = protocol_path.parent
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    entry = protocol["splits"]["independent_test"]
    rows = []
    for name in ("queries", "qrels"):
        path = (directory / entry[name]).resolve()
        if not path.is_relative_to(directory) or digest(path) != entry[f"{name}_sha256"]:
            raise ValueError(f"Independent test {name} is not sealed")
        rows.append([json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                     if line.strip()])
    return rows


def _summarize(rows):
    answer = [row for row in rows if row["has_answer"]]
    noanswer = [row for row in rows if not row["has_answer"]]
    returned = sum(row["status"] == "evidence_found" for row in noanswer)
    refused = sum(row["status"] != "evidence_found" for row in answer)
    return {
        "queries": len(rows), "answerable": len(answer), "no_answer": len(noanswer),
        "no_answer_false_return_count": returned,
        "no_answer_false_return_rate": returned / len(noanswer) if noanswer else None,
        "answer_false_refusal_count": refused,
        "answer_false_refusal_rate": refused / len(answer) if answer else None,
        "recall": statistics.fmean(row["recall"] for row in answer) if answer else None,
        "mrr": statistics.fmean(row["mrr"] for row in answer) if answer else None,
        "ndcg": statistics.fmean(row["ndcg"] for row in answer) if answer else None,
    }


def _groups(result, queries):
    by_id = {row["query_id"]: row for row in queries}
    groups = {"product_version": defaultdict(list), "component": defaultdict(list)}
    for row in result["queries"]:
        query = by_id[row["query_id"]]
        groups["product_version"][query["product_version"]].append(row)
        groups["component"][query.get("component") or "unspecified"].append(row)
    return {dimension: {value: _summarize(items) for value, items in sorted(group.items())}
            for dimension, group in groups.items()}


def run(agent_config, protocol_path, calibration_path, service_config_path,
        release_dir, output_dir):
    """Refuse unreviewed data, then write one immutable blind-test result directory."""
    readiness = validate_protocol(protocol_path, require_release_ready=True)
    cfg = load_agent(agent_config)
    candidate = verify_candidate(cfg, protocol_path, calibration_path,
                                 service_config_path, release_dir)
    if candidate["status"] != "READY_FOR_ACCEPTANCE":
        raise ValueError("Candidate is not ready for independent acceptance")
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError("Blind test output already exists; choose a new directory")
    queries, qrels = _read_sealed_test(protocol_path)
    frozen = FrozenRetriever(cfg["rag"]["retrieval"])
    gated = CandidateRetriever(frozen, candidate["gate_threshold"])
    mode, top_k = frozen.manifest["default_mode"], frozen.manifest["default_k"]
    baseline = evaluate(frozen, queries, qrels, mode, top_k, apply_gate=True)
    proposed = evaluate(gated, queries, qrels, mode, top_k, apply_gate=True)
    result = {
        "schema_version": 1, "status": "INDEPENDENT_RETRIEVAL_EVALUATION",
        "candidate_release_id": candidate["release_id"],
        "kb_release_id": candidate["kb_release_id"],
        "protocol_sha256": digest(protocol_path),
        "calibration_sha256": digest(calibration_path),
        "readiness": readiness,
        "baseline": {"metrics": baseline["metrics"],
                     "counts": _summarize(baseline["queries"]),
                     "groups": _groups(baseline, queries)},
        "candidate": {"metrics": proposed["metrics"],
                      "counts": _summarize(proposed["queries"]),
                      "groups": _groups(proposed, queries)},
        "cases": [{"query_id": query["query_id"], "product_version": query["product_version"],
                   "component": query.get("component"), "has_answer": query["has_answer"],
                   "baseline": baseline["queries"][index],
                   "candidate": proposed["queries"][index]}
                  for index, query in enumerate(queries)],
    }
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = output_dir.parent / f".{output_dir.name}.{uuid.uuid4().hex}.partial"
    try:
        staging.mkdir()
        save(staging / "result.json", result)
        save(staging / "manifest.json", {"schema_version": 1,
             "artifacts": {"result.json": digest(staging / "result.json")}})
        os.replace(staging, output_dir)
    finally:
        if staging.exists() and staging.resolve().parent == output_dir.parent.resolve():
            shutil.rmtree(staging)
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("agent_config", "protocol", "calibration", "service_config",
                 "candidate_release", "output_dir"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    value = run(args.agent_config, args.protocol, args.calibration,
                args.service_config, args.candidate_release, args.output_dir)
    print(json.dumps({"candidate_release_id": value["candidate_release_id"],
                      "baseline": value["baseline"]["counts"],
                      "candidate": value["candidate"]["counts"]}, ensure_ascii=False))
