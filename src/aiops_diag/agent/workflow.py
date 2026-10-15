import json
import time
from collections import Counter
from pathlib import Path

from .schemas import RouterDecision
from .engine import ROUTER_PROMPT


def load_cases(path):
    rows = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()]
    if len(rows) != 20 or len({row["case_id"] for row in rows}) != 20:
        raise ValueError("Adev must contain exactly 20 unique cases")
    expected = {"routine": 6, "normal_context": 3, "insufficient_evidence": 3,
                "high_risk": 3, "failure_recovery": 2, "prompt_injection": 2,
                "approval_conflict": 1}
    if dict(Counter(row.get("category") for row in rows)) != expected:
        raise ValueError("Adev category composition changed")
    return rows


def deterministic_status(case):
    review = (not case["evidence_available"] or case["risk"] in ("high", "unknown")
              or case["confidence"] in ("low", "unknown") or case["injection"]
              or case["tool_failure"] or case["approval_conflict"])
    return "WAITING_REVIEW" if review else "COMPLETED"


def evaluate(cfg, online=False, client=None):
    cases = load_cases(cfg["paths"]["adev"])
    results = []
    optional_correct = 0
    online_calls = 0
    started = time.perf_counter()
    baseline = client.ledger.read() if online and client is not None else None
    stopped_by_budget = False
    for case in cases:
        predicted = deterministic_status(case)
        optional = []
        error = None
        if online and client is not None:
            current = client.ledger.read()
            used_tokens = ((current["input_tokens"] + current["output_tokens"])
                           - (baseline["input_tokens"] + baseline["output_tokens"]))
            used_cost = current["estimated_cost_cny"] - baseline["estimated_cost_cny"]
            if (used_tokens >= int(cfg["evaluation"]["max_tokens"])
                    or used_cost >= float(cfg["evaluation"]["max_cost_cny"])):
                stopped_by_budget = True
                results.append({"case_id": case["case_id"],
                                "expected_status": case["expected_status"],
                                "actual_status": predicted, "optional_tools": [],
                                "expected_optional_tools": case["expected_optional_tools"],
                                "error": "EVALUATION_BUDGET_EXHAUSTED"})
                continue
            package = {name: case[name] for name in (
                "category", "anomaly", "evidence_available", "risk", "confidence")}
            try:
                raw, _usage = client.complete_json([
                    {"role": "system", "content": ROUTER_PROMPT},
                    {"role": "user", "content": json.dumps(package, ensure_ascii=False)},
                ])
                optional = RouterDecision.model_validate(raw).next_tools
                online_calls += 1
            except Exception as exc:
                error = type(exc).__name__
        if set(optional) == set(case["expected_optional_tools"]):
            optional_correct += 1
        results.append({"case_id": case["case_id"], "expected_status": case["expected_status"],
                        "actual_status": predicted, "optional_tools": optional,
                        "expected_optional_tools": case["expected_optional_tools"],
                        "error": error})
    mandatory = [row for row in cases if row["expected_status"] == "WAITING_REVIEW"]
    mandatory_hits = sum(deterministic_status(row) == "WAITING_REVIEW" for row in mandatory)
    final_usage = client.ledger.read() if online and client is not None else None
    usage_delta = None
    if baseline is not None and final_usage is not None:
        usage_delta = {
            "input_tokens": final_usage["input_tokens"] - baseline["input_tokens"],
            "output_tokens": final_usage["output_tokens"] - baseline["output_tokens"],
            "estimated_cost_cny": round(
                final_usage["estimated_cost_cny"] - baseline["estimated_cost_cny"], 8),
        }
    summary = {"schema_version": 1, "cases": len(cases),
               "terminal_accuracy": sum(row["expected_status"] == row["actual_status"]
                                        for row in results) / len(results),
               "mandatory_review_recall": mandatory_hits / len(mandatory),
               "optional_tool_accuracy": optional_correct / len(cases) if online else None,
               "online_calls": online_calls,
               "usage_delta": usage_delta,
               "stopped_by_budget": stopped_by_budget,
               "elapsed_ms": (time.perf_counter() - started) * 1000,
               "results": results}
    work = Path(cfg["paths"]["work_dir"])
    work.mkdir(parents=True, exist_ok=True)
    target = work / ("adev_online.json" if online else "adev_replay.json")
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary
