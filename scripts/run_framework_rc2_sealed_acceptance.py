"""Run the frozen 30-case RC2 acceptance exactly once."""

import argparse
import json
import math
import os
import statistics
from datetime import datetime, timezone
from pathlib import Path

from aiops_diag.comparison.offline_framework import run
from aiops_diag.data.common import digest


ROOT = Path(__file__).resolve().parents[1]


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def percentile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    position = (len(values) - 1) * fraction
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return values[low]
    return values[low] + (values[high] - values[low]) * (position - low)


def ranking_metrics(case, expected):
    merged = []
    for retrieval in case["backends"]["framework_candidate"]["normalized"]["retrievals"]:
        for item in retrieval["items"]:
            if item["chunk_id"] not in merged:
                merged.append(item["chunk_id"])
    relevant = set(expected)
    ranks = [index for index, chunk_id in enumerate(merged, 1) if chunk_id in relevant]
    recall = len(set(merged) & relevant) / len(relevant) if relevant else None
    mrr = 1.0 / min(ranks) if ranks else 0.0
    dcg = sum(1.0 / math.log2(rank + 1) for rank in ranks)
    ideal = sum(1.0 / math.log2(index + 1)
                for index in range(1, min(len(relevant), len(merged)) + 1))
    return recall, mrr, dcg / ideal if ideal else 0.0, merged


def render(result):
    m = result["metrics"]
    g = result["gates"]
    lines = [
        "# Framework RC2 30 例一次性封存验收", "",
        f"- 正式运行时间：`{result['official_run_started_at']}`",
        f"- 候选发布：`{result['framework_release_id']}`",
        "- 该集合现已揭盲，不得用于后续调参或再次正式验收。",
        "- F/G/H 是流程隔离的 AI 角色，并非身份核验的自然人。", "",
        "## 指标", "",
        f"- 流程完成：{m['flow_completed_count']}/30",
        f"- 有答案错误拒答：{m['answer_false_refusal_count']}/18",
        f"- 知识库外错误返回：{m['no_answer_false_return_count']}/12 "
        f"（{m['no_answer_false_return_rate']:.2%}）",
        f"- Recall / MRR / NDCG：{m['recall']:.4f} / {m['mrr']:.4f} / {m['ndcg']:.4f}",
        f"- Schema 合法：{m['schema_valid_count']}/30",
        f"- 模板降级：{m['template_fallback_count']}/30",
        f"- legacy/framework 等价：{m['parity_count']}/30",
        f"- Framework LLM 调用 / tokens / 费用：{m['llm_calls']} / {m['tokens']} / "
        f"{m['estimated_cost_cny']:.8f} CNY",
        f"- Framework 耗时 P50 / P95：{m['p50_ms']:.3f} / {m['p95_ms']:.3f} ms", "",
        "## 发布门禁", "",
    ]
    lines.extend(f"- {name}：`{value}`" for name, value in g.items())
    lines.extend(["", f"最终判定：`{'PASS' if result['passed'] else 'REJECT'}`。", ""])
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set-dir", type=Path,
                        default=ROOT / "evaluation/v1.1/framework_rc2_sealed_20261020")
    parser.add_argument("--legacy-config", type=Path,
                        default=ROOT / "configs/service_v11_framework_base_rc2.yaml")
    parser.add_argument("--framework-config", type=Path,
                        default=ROOT / "configs/service_framework_rc2.yaml")
    parser.add_argument("--recovery-report", type=Path, default=ROOT / "deliverables/results/"
                        "framework_fault_recovery_acceptance_rc2.json")
    parser.add_argument("--work-dir", type=Path,
                        default=ROOT / "runtime/framework_rc2_sealed_once")
    parser.add_argument("--output", type=Path, default=ROOT / "deliverables/results/"
                        "framework_sealed_acceptance_rc2_once.json")
    parser.add_argument("--markdown", type=Path, default=ROOT / "deliverables/results/"
                        "framework_sealed_acceptance_rc2_once.md")
    options = parser.parse_args()
    set_dir = options.set_dir.resolve()
    marker = set_dir / "official_run_started.json"
    if marker.exists() or options.output.exists():
        raise SystemExit("Official RC2 sealed acceptance has already been started")
    events = read_jsonl(set_dir / "independent_test.jsonl")
    qrels = {row["case_id"]: row for row in read_jsonl(
        set_dir / "independent_test_qrels.jsonl")}
    if len(events) != 30 or len(qrels) != 30:
        raise SystemExit("The sealed set must contain exactly 30 events and qrels")
    recovery = json.loads(options.recovery_report.read_text(encoding="utf-8"))
    if not recovery.get("passed"):
        raise SystemExit("Fault and recovery acceptance must pass before the official run")
    started = datetime.now(timezone.utc).isoformat()
    fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump({"schema_version": 1, "started_at": started,
                   "status": "OFFICIAL_RUN_STARTED_NO_RERUN"}, stream, indent=2)
        stream.write("\n")
    options.work_dir.mkdir(parents=True, exist_ok=True)
    joined = options.work_dir / "sealed_joined_revealed_for_runner.jsonl"
    with joined.open("w", encoding="utf-8") as stream:
        for event in events:
            label = qrels[event["case_id"]]
            value = {**event, "source": "real_index_synthetic_development",
                     "retrieval_fixture": "live",
                     "expected_diagnosis_status": (
                         "EVIDENCE_SUPPORTED" if label["has_answer"]
                         else "INSUFFICIENT_EVIDENCE"),
                     "expected_review_reasons": (
                         ["prompt_injection"] if "injection" in event["coverage_tags"]
                         else [] if label["has_answer"]
                         else ["insufficient_evidence", "unknown_confidence"])}
            stream.write(json.dumps(value, ensure_ascii=False) + "\n")
    comparison = run(joined, options.legacy_config, options.framework_config,
                     options.work_dir / "paired", None, None)
    recalls, mrrs, ndcgs, cases = [], [], [], []
    answer_false, no_answer_false = 0, 0
    schema_valid = template_fallback = flow_complete = 0
    elapsed = []
    llm_calls = tokens = 0
    cost = 0.0
    for case in comparison["cases"]:
        label = qrels[case["case_id"]]
        backend = case["backends"]["framework_candidate"]
        normalized = backend["normalized"]
        report = normalized.get("report") or {}
        returned = report.get("diagnosis_status") == "EVIDENCE_SUPPORTED"
        flow_complete += int(normalized["terminal_status"] in {
            "WAITING_REVIEW", "COMPLETED", "APPROVED_REPORT"} and bool(report))
        schema_valid += int(bool(report))
        template_fallback += int(report.get("diagnosis_status") == "DEGRADED_TEMPLATE")
        if label["has_answer"]:
            answer_false += int(not returned)
            recall, mrr, ndcg, merged = ranking_metrics(
                case, label["expected_chunk_ids"])
            recalls.append(recall); mrrs.append(mrr); ndcgs.append(ndcg)
        else:
            no_answer_false += int(returned)
            merged = [item["chunk_id"] for value in normalized["retrievals"]
                      for item in value["items"]]
        budget = normalized["budget"]
        llm_calls += budget["llm_calls"]
        tokens += budget["tokens"]
        cost += budget["estimated_cost_cny"]
        elapsed.append(backend["elapsed_ms"])
        cases.append({"case_id": case["case_id"], "has_answer": label["has_answer"],
                      "diagnosis_status": report.get("diagnosis_status"),
                      "retrieved_chunk_ids": merged,
                      "parity_passed": case["parity_passed"],
                      "differences": case["differences"]})
    hard = dict(comparison["hard_gate_counts"])
    hard["duplicate_paid_calls_after_recovery"] = recovery["hard_gate_counts"][
        "duplicate_paid_calls_after_recovery"]
    hard["conflicting_reports_or_approvals_after_recovery"] = recovery[
        "hard_gate_counts"]["conflicting_reports_or_approvals_after_recovery"]
    metrics = {
        "flow_completed_count": flow_complete,
        "answer_false_refusal_count": answer_false,
        "no_answer_false_return_count": no_answer_false,
        "no_answer_false_return_rate": no_answer_false / 12,
        "recall": statistics.mean(recalls), "mrr": statistics.mean(mrrs),
        "ndcg": statistics.mean(ndcgs), "schema_valid_count": schema_valid,
        "template_fallback_count": template_fallback,
        "parity_count": sum(case["parity_passed"] for case in comparison["cases"]),
        "llm_calls": llm_calls, "tokens": tokens,
        "estimated_cost_cny": round(cost, 8),
        "p50_ms": percentile(elapsed, 0.50), "p95_ms": percentile(elapsed, 0.95),
    }
    gates = {
        "thirty_of_thirty_flow_completed": flow_complete == 30,
        "framework_adds_no_crash_or_safety_failure": not any(hard.values()),
        "all_differences_attributed": all(case["parity_passed"]
                                          or bool(case["differences"])
                                          for case in comparison["cases"]),
        "six_primary_and_two_recovery_hard_gates_zero": not any(hard.values()),
    }
    result = {
        "schema_version": 1, "status": "RC2_SEALED_ACCEPTANCE_ONCE",
        "official_run_started_at": started,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "revealed_after_run": True, "reusable_for_tuning_or_acceptance": False,
        "identity_verified_human_reviewers": False,
        "old_revealed_60_used": False,
        "framework_release_id": comparison["layers"]["framework_candidate"]
        if "layers" in comparison else comparison["cases"][0]["backends"][
            "framework_candidate"]["release_id"],
        "set_hashes": {name: digest(set_dir / name) for name in (
            "independent_test.jsonl", "independent_test_qrels.jsonl", "protocol.json",
            "creator_f_submission.jsonl", "reviewer_g_submission.jsonl",
            "adjudication_h.jsonl", "pollution_audit.md")},
        "comparison_case_set_sha256": digest(joined),
        "metrics": metrics, "hard_gate_counts": hard, "gates": gates,
        "passed": all(gates.values()), "cases": cases,
    }
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    options.markdown.write_text(render(result), encoding="utf-8")
    print(json.dumps({"status": result["status"], "passed": result["passed"],
                      "metrics": metrics, "hard_gate_counts": hard},
                     ensure_ascii=False, indent=2))
