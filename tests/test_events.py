"""验证异常门禁与会话事件构建。"""

from aiops_diag.platform.events import build_event, gate_session, score_rows


# 验证错误日志通过门禁。
def test_gate_passes_error_rows():
    rows = [{"level": "ERROR", "redacted_message": "No space left on device"}]
    decision = gate_session(rows, 0.6)
    assert decision["decision"] == "PASS"
    assert decision["score"] >= 0.6


# 验证普通 INFO 日志被拒绝。
def test_gate_rejects_normal_rows():
    rows = [{"level": "INFO", "redacted_message": "DataNode started"}]
    decision = gate_session(rows, 0.6)
    assert decision["decision"] == "REJECT"
    assert decision["reason"] == "below_threshold"


# 验证安全模式关键词能触发门禁。
def test_gate_detects_safe_mode():
    rows = [{"level": "INFO", "redacted_message": "Safe mode is ON"}]
    assert gate_session(rows, 0.6)["decision"] == "PASS"


# 验证事件字段完整。
def test_build_event_keeps_gate_provenance():
    rows = [{"level": "ERROR", "redacted_message": "failed volume"}]
    score = score_rows(rows)
    event = build_event("evt_1", "bat_1", "ses_1", rows, score, 0.6,
                        "DataNode", "t0", "t1", "t2")
    assert event["event_id"] == "evt_1"
    assert event["max_anomaly_score"] == score
    assert event["threshold"] == 0.6
    assert event["session_count"] == 1
