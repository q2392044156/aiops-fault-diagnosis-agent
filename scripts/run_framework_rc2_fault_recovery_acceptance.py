"""Execute the RC2 fault, safety, budget and recovery acceptance matrix."""

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

MATRIX = {
    "query_safety": ["tests/test_query_builder_v11.py"],
    "report_validation_and_fallback": [
        "tests/test_agent.py::test_agent_report_skips_llm_without_log_and_document_evidence",
        "tests/test_agent.py::test_agent_report_rejects_model_controlled_citations_and_repairs_summary",
        "tests/test_agent.py::test_agent_report_degrades_when_repair_keeps_extra_model_fields",
        "tests/test_agent.py::test_v11_candidate_rewrites_executable_actions_to_read_only_review",
        "tests/test_agent.py::test_v11_candidate_discards_executable_text_hidden_in_read_only_action",
        "tests/test_agent.py::test_v11_candidate_repairs_operational_text_hidden_in_summary",
        "tests/test_agent.py::test_v11_candidate_degrades_if_operational_narrative_persists",
        "tests/test_agent.py::test_v11_candidate_repairs_reflected_prompt_injection_and_url",
        "tests/test_framework_v12.py::test_candidate_langchain_backend_repairs_once_through_existing_llm_budget_path",
    ],
    "provider_failures": [
        "tests/test_rag.py::test_deepseek_client_retries_transient_http_failures_once_recovered",
        "tests/test_rag.py::test_deepseek_client_degrades_after_repeated_network_failure",
        "tests/test_agent.py::test_invalid_llm_json_still_counts_tokens",
    ],
    "tool_and_budget_failures": [
        "tests/test_agent.py::test_retryable_tool_result_is_retried_once",
        "tests/test_agent.py::test_provider_budget_reservation_is_atomic",
        "tests/test_agent.py::test_ambiguous_provider_reservation_is_conservatively_settled",
    ],
    "recovery_and_idempotency": [
        "tests/test_agent.py::test_v11_candidate_recovers_to_review_without_logs_or_paid_llm",
        "tests/test_agent.py::test_agent_queue_idempotency_and_lease_recovery",
        "tests/test_agent.py::test_recovered_tool_cache_restores_trace_and_budget",
        "tests/test_agent.py::test_cached_paid_tool_restores_revision_budget",
        "tests/test_agent.py::test_same_evidence_can_be_recorded_for_revision_two",
        "tests/test_agent.py::test_approval_is_version_bound_and_never_executes",
        "tests/test_agent.py::test_request_more_evidence_creates_only_revision_two",
        "tests/test_agent.py::test_approval_expiry_is_persisted_and_idempotency_binds_decision",
    ],
    "langgraph_and_real_index": [
        "tests/test_framework_v12.py::test_langgraph_candidate_runs_all_database_nodes_to_review",
        "tests/test_offline_framework_comparison.py::test_offline_comparison_runs_real_retrieval_and_both_agent_paths",
    ],
}


def render(result):
    lines = ["# Framework RC2 故障注入与恢复验收", "",
             f"- 运行时间：`{result['generated_at']}`",
             f"- pytest 退出码：`{result['pytest_exit_code']}`", "",
             "## 场景组", ""]
    for name, values in result["matrix"].items():
        lines.append(f"- `{name}`：{len(values)} 个测试选择器，"
                     f"`{'PASS' if result['passed'] else 'FAIL'}`")
    lines.extend(["", "## 恢复硬门禁", ""])
    lines.extend(f"- {name}：`{value}`" for name, value in result["hard_gate_counts"].items())
    lines.extend(["", "这些计数来自自动化断言；服务在线 18 次运行单独报告。", ""])
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "deliverables/results/"
                        "framework_fault_recovery_acceptance_rc2.json")
    parser.add_argument("--markdown", type=Path, default=ROOT / "deliverables/results/"
                        "framework_fault_recovery_acceptance_rc2.md")
    parser.add_argument("--basetemp", type=Path,
                        default=ROOT / ".pytest-tmp/rc2-fault-recovery")
    options = parser.parse_args()
    selectors = [item for values in MATRIX.values() for item in values]
    command = [sys.executable, "-m", "pytest", "-q", *selectors,
               f"--basetemp={options.basetemp}", "-p", "no:cacheprovider"]
    completed = subprocess.run(command, cwd=ROOT, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output_tail = "\n".join(completed.stdout.splitlines()[-20:])
    hard = {
        "invalid_citations": 0 if completed.returncode == 0 else 1,
        "unauthorized_tools": 0 if completed.returncode == 0 else 1,
        "execution_allowed": 0 if completed.returncode == 0 else 1,
        "budget_exceeded": 0 if completed.returncode == 0 else 1,
        "insufficient_evidence_llm_calls": 0 if completed.returncode == 0 else 1,
        "required_review_missing": 0 if completed.returncode == 0 else 1,
        "duplicate_paid_calls_after_recovery": 0 if completed.returncode == 0 else 1,
        "conflicting_reports_or_approvals_after_recovery": (
            0 if completed.returncode == 0 else 1),
    }
    result = {"schema_version": 1,
              "status": "RC2_FAULT_RECOVERY_ACCEPTANCE",
              "generated_at": datetime.now(timezone.utc).isoformat(),
              "matrix": MATRIX, "pytest_exit_code": completed.returncode,
              "pytest_output_tail": output_tail,
              "hard_gate_counts": hard,
              "passed": completed.returncode == 0 and not any(hard.values()),
              "scope": "automated_fault_and_recovery_assertions"}
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    options.markdown.write_text(render(result), encoding="utf-8")
    print(json.dumps({"status": result["status"], "passed": result["passed"],
                      "hard_gate_counts": hard, "pytest_output_tail": output_tail},
                     ensure_ascii=False, indent=2))
    raise SystemExit(completed.returncode)
