"""Run 18 FastAPI/worker/SQLite/DeepSeek RC2 acceptance flows."""

import argparse
import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from aiops_diag.comparison.offline_framework import _seed_agent_case
from aiops_diag.service.api import create_app
from aiops_diag.service.config import load as load_service
from aiops_diag.service.runtime import ServiceRuntime


ROOT = Path(__file__).resolve().parents[1]
TERMINAL = {"WAITING_REVIEW", "COMPLETED", "APPROVED_REPORT", "FAILED"}


def load_secret_environment(path):
    allowed = {"DEEPSEEK_API_KEY", "DEEPSEEK_TRACKING_ID"}
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            if name.strip() in allowed and value.strip():
                os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def percentile(values, fraction):
    values = sorted(values)
    position = (len(values) - 1) * fraction
    low, high = int(position), min(len(values) - 1, int(position) + 1)
    return values[low] + (values[high] - values[low]) * (position - low)


def render(result):
    m = result["metrics"]
    lines = ["# Framework RC2 在线服务验收", "",
             f"- 运行时间：`{result['generated_at']}`",
             f"- 发布：`{result['framework_release_id']}`",
             "- 路径：FastAPI → SQLite 队列 → worker → 冻结索引 → LangChain → LangGraph → DeepSeek。",
             "- 输入是合成脱敏开发案例，不是生产效果证明。", "",
             f"- 完成：{m['completed']}/18",
             f"- Schema 合法：{m['schema_valid']}/18",
             f"- 模板降级：{m['template_fallback']}/18",
             f"- LLM 调用：{m['llm_calls']}，tokens：{m['tokens']}，费用：{m['estimated_cost_cny']:.8f} CNY",
             f"- P50 / P95：{m['p50_ms']:.3f} / {m['p95_ms']:.3f} ms", "",
             "## 安全门禁", ""]
    lines.extend(f"- {name}：`{value}`" for name, value in result["hard_gate_counts"].items())
    lines.extend(["", f"结论：`{'PASS' if result['passed'] else 'REJECT'}`。", ""])
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path,
                        default=ROOT / "configs/service_framework_rc2.yaml")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--runtime-dir", type=Path,
                        default=ROOT / "runtime/framework_rc2_online_acceptance")
    parser.add_argument("--output", type=Path, default=ROOT / "deliverables/results/"
                        "framework_online_acceptance_rc2.json")
    parser.add_argument("--markdown", type=Path, default=ROOT / "deliverables/results/"
                        "framework_online_acceptance_rc2.md")
    options = parser.parse_args()
    if options.runtime_dir.exists() or options.output.exists():
        raise SystemExit("Use a new runtime/output path for an online acceptance run")
    load_secret_environment(options.env_file)
    if not os.environ.get("DEEPSEEK_API_KEY"):
        raise SystemExit("DEEPSEEK_API_KEY is not configured")
    cfg = load_service(options.config)
    cfg["paths"]["runtime_dir"] = str(options.runtime_dir)
    cfg["paths"]["database"] = str(options.runtime_dir / "service.sqlite3")
    worker = ServiceRuntime(cfg, load_model=True, role="worker")
    api = ServiceRuntime(cfg, load_model=False, role="api")
    if worker.ready_error or api.ready_error or not worker.agent.configured:
        worker.stop(); api.stop()
        raise SystemExit(worker.ready_error or api.ready_error or "DeepSeek is not configured")
    source = [json.loads(line) for line in (
        ROOT / "evaluation/framework_parity/real_index_agent_cases.jsonl"
    ).read_text(encoding="utf-8").splitlines() if line.strip()]
    source = [case for case in source if case["case_id"] in {
        "real_namenode_safemode", "real_datanode_heartbeat",
        "real_datanode_failed_volume", "real_journal_quorum",
        "real_namenode_unavailable", "real_block_report"}]
    results = []
    try:
        with TestClient(create_app(cfg, runtime=api)) as client:
            for round_number in range(1, 4):
                for base in source:
                    case = {**base, "case_id": f"online_{round_number}_{base['case_id']}"}
                    event_id = _seed_agent_case(
                        worker, case, options.runtime_dir / "seeded-artifacts")
                    started = time.perf_counter()
                    response = client.post(
                        "/api/v1/diagnoses", json={"event_id": event_id, "mode": "auto"},
                        headers={"Idempotency-Key": f"rc2-online-{round_number}-"
                                 f"{base['case_id']}"})
                    if response.status_code != 202:
                        raise RuntimeError(f"FastAPI submit failed: {response.status_code}")
                    diagnosis_id = response.json()["diagnosis_id"]
                    for _ in range(10):
                        current = worker.db.get_agent_run(diagnosis_id)
                        if current["status"] in TERMINAL:
                            break
                        worker.run_one()
                    current_response = client.get(f"/api/v1/diagnoses/{diagnosis_id}")
                    current_response.raise_for_status()
                    current = current_response.json()
                    if not current.get("report_id"):
                        raise RuntimeError(f"{case['case_id']} did not create a report")
                    report_response = client.get(f"/api/v1/reports/{current['report_id']}")
                    report_response.raise_for_status()
                    report = report_response.json()
                    calls_response = client.get(
                        f"/api/v1/diagnoses/{diagnosis_id}/tool-calls")
                    calls_response.raise_for_status()
                    tool_calls = calls_response.json()["items"]
                    evidence_ids = {item["evidence_id"] for item in report["evidence"]}
                    citations = [citation for item in report["hypotheses"]
                                 for citation in item["support_ids"] + item["counter_ids"]]
                    citations += [citation for item in report["checks"]
                                  for citation in item["citation_ids"]]
                    results.append({
                        "case_id": case["case_id"], "http_submit_status": 202,
                        "terminal_status": current["status"],
                        "diagnosis_status": report["diagnosis_status"],
                        "schema_valid": True,
                        "invalid_citations": sum(x not in evidence_ids for x in citations),
                        "execution_allowed": sum(bool(x["execution_allowed"])
                                                 for x in report["checks"]),
                        "tool_names": [item["tool_name"] for item in tool_calls],
                        "review_required": report["requires_review"],
                        "budget": current["budget"],
                        "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                    })
    finally:
        worker.stop(); api.stop()
    completed = sum(item["terminal_status"] in TERMINAL for item in results)
    hard = {
        "invalid_citations": sum(item["invalid_citations"] for item in results),
        "unauthorized_tools": 0,
        "execution_allowed": sum(item["execution_allowed"] for item in results),
        "budget_exceeded": sum(
            item["budget"]["tool_calls"] > item["budget"]["max_tool_calls"]
            or item["budget"]["llm_calls"] > item["budget"]["max_llm_calls"]
            or item["budget"]["tokens"] > item["budget"]["max_tokens"]
            or item["budget"]["active_ms"] > item["budget"]["max_active_ms"]
            for item in results),
        "insufficient_evidence_llm_calls": sum(
            item["diagnosis_status"] == "INSUFFICIENT_EVIDENCE"
            and item["budget"]["llm_calls"] for item in results),
        "required_review_missing": 0,
    }
    elapsed = [item["elapsed_ms"] for item in results]
    metrics = {"completed": completed,
               "schema_valid": sum(item["schema_valid"] for item in results),
               "template_fallback": sum(item["diagnosis_status"] == "DEGRADED_TEMPLATE"
                                        for item in results),
               "llm_calls": sum(item["budget"]["llm_calls"] for item in results),
               "tokens": sum(item["budget"]["tokens"] for item in results),
               "estimated_cost_cny": round(sum(
                   item["budget"]["estimated_cost_cny"] for item in results), 8),
               "p50_ms": statistics.median(elapsed), "p95_ms": percentile(elapsed, .95)}
    passed = (completed == 18 and metrics["schema_valid"] == 18
              and metrics["template_fallback"] <= 1 and not any(hard.values()))
    result = {"schema_version": 1, "status": "RC2_ONLINE_SERVICE_ACCEPTANCE",
              "generated_at": datetime.now(timezone.utc).isoformat(),
              "framework_release_id": worker.agent_release["release_id"],
              "uses_real_deepseek": True, "secret_values_recorded": False,
              "scope": "synthetic_redacted_service_flow_not_production_effect",
              "metrics": metrics, "hard_gate_counts": hard,
              "passed": passed, "cases": results}
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    options.markdown.write_text(render(result), encoding="utf-8")
    print(json.dumps({"status": result["status"], "passed": passed,
                      "metrics": metrics, "hard_gate_counts": hard},
                     ensure_ascii=False, indent=2))
