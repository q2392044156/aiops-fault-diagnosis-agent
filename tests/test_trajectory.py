"""模块说明：验证轨迹指标、失败分类与汇总计算。"""

import json

from aiops_diag.evaluation.trajectory import (aggregate, markdown, pass_pow_k,
                                              summarize)


# 方法说明：_run 构造一条 agent_runs 记录，预算与状态可覆盖。
def _run(status="APPROVED_REPORT", node="REPORT_VALIDATED", tokens=1000,
         active_ms=1000, llm_calls=2, max_tokens=12000, max_active_ms=120000, state=None):
    return {"diagnosis_id": "dia_1", "revision": 1, "mode": "auto", "status": status,
            "current_node": node, "state_json": json.dumps(state or {}),
            "budget_json": json.dumps({"tokens": tokens, "max_tokens": max_tokens,
                                       "active_ms": active_ms,
                                       "max_active_ms": max_active_ms,
                                       "llm_calls": llm_calls,
                                       "estimated_cost_cny": 0.01})}


# 方法说明：_call 构造一条工具调用记录。
def _call(name, status="SUCCEEDED", args_hash="h"):
    return {"tool_name": name, "status": status, "args_hash": args_hash, "ordinal": 1}


# 方法说明：_report 构造一份含引用与证据的报告。
def _report(cited=("evd_1",), evidence=("evd_1", "evd_2"),
            status="EVIDENCE_SUPPORTED", reasons=(), requires_review=False):
    return {"diagnosis_status": status, "requires_review": requires_review,
            "review_reasons": list(reasons),
            "evidence": [{"evidence_id": item} for item in evidence],
            "hypotheses": [{"support_ids": list(cited), "counter_ids": []}],
            "checks": [{"citation_ids": []}]}


# 方法说明：test_clean_run_has_no_flags 验证正常轨迹的判定与覆盖率。
def test_clean_run_has_no_flags():
    row = summarize(_run(), [_call("detect_anomaly"), _call("query_logs")], _report())
    assert row["verdict"] == "clean"
    assert row["steps"] == 7
    assert row["tool_calls"] == 2
    assert row["flags"] == []
    assert row["evidence_coverage"] == 0.5


# 方法说明：test_retry_loop_is_detected 验证相同工具与参数被重复调用时标记重试。
def test_retry_loop_is_detected():
    calls = [_call("query_logs", args_hash="a"), _call("query_logs", args_hash="a")]
    row = summarize(_run(), calls, _report())
    assert row["retries"] == 1
    assert "retry_loop" in row["flags"]


# 方法说明：test_failed_tool_with_report_is_recovered 验证失败后仍产出报告算“已恢复”。
def test_failed_tool_with_report_is_recovered():
    calls = [_call("query_logs", status="FAILED"), _call("retrieve_runbook")]
    row = summarize(_run(), calls, _report())
    assert row["verdict"] == "recovered"
    assert row["failed_calls"] == 1
    assert "tool_failure" in row["flags"]


# 方法说明：test_degraded_report_and_missing_report 验证模板降级与无报告的判定。
def test_degraded_report_and_missing_report():
    degraded = summarize(_run(), [_call("generate_incident_report")],
                         _report(evidence=(), cited=(), status="DEGRADED_TEMPLATE"))
    assert degraded["verdict"] == "degraded"
    assert "no_evidence" not in degraded["flags"]
    assert "degraded_report" in degraded["flags"]
    abstained = summarize(_run(), [_call("retrieve_runbook")],
                          _report(evidence=(), cited=(), status="INSUFFICIENT_EVIDENCE"))
    assert abstained["verdict"] == "abstained"
    assert abstained["flags"] == []
    failed = summarize(_run(status="FAILED"), [], None)
    assert failed["verdict"] == "failed"


# 方法说明：test_ungrounded_citation_and_budget_pressure 验证越权引用与预算压力标记。
def test_ungrounded_citation_and_budget_pressure():
    row = summarize(_run(tokens=11000), [_call("generate_incident_report")],
                    _report(cited=("evd_x",)))
    assert row["ungrounded_citations"] == ["evd_x"]
    assert "ungrounded_citation" in row["flags"]
    assert "budget_pressure" in row["flags"]


# 方法说明：test_aggregate_and_pass_pow_k 验证汇总比率与 pass^k。
def test_aggregate_and_pass_pow_k():
    rows = [
        summarize(_run(), [_call("query_logs")], _report()),
        summarize(_run(), [_call("query_logs"), _call("query_logs")], _report()),
        summarize(_run(status="FAILED"), [], None),
    ]
    summary = aggregate(rows)
    assert summary["runs"] == 3
    assert summary["verdicts"] == {"clean": 2, "failed": 1}
    assert 0.0 <= summary["retry_rate"] <= 1.0
    assert pass_pow_k([[True, True], [True, False], [True, True]]) == 0.6667
    assert pass_pow_k([[True], [True]]) == 1.0


# 方法说明：test_markdown_contains_run_and_summary 验证 Markdown 输出包含关键行。
def test_markdown_contains_run_and_summary():
    rows = [summarize(_run(), [_call("query_logs")], _report())]
    table = markdown(rows, aggregate(rows))
    assert "dia_1" in table
    assert "## 汇总" in table
    assert "平均工具调用" in table
