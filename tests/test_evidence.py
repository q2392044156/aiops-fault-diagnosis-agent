"""模块说明：验证证据级评测的关键证据规则。"""

from aiops_diag.diagnosis.engine import evidence_sufficiency, select_log_rows
from ops.lab.harness.evidence import gold_ids


# 方法说明：构造证据行。
def _row(log_id, message, level="INFO"):
    return {"log_id": log_id, "message": message, "level": level}


# 方法说明：验证卷故障信号行被标为关键证据。
def test_volume_gold_matches_no_space():
    incident = {"labels": {"root_cause_code": "DN_VOLUME"}}
    rows = [_row("a", "No space left on device", "ERROR"),
            _row("b", "Scheduled metric snapshot")]
    assert gold_ids(incident, rows) == ["a"]


# 方法说明：验证心跳信号行被标为关键证据。
def test_heartbeat_gold_matches_lost_datanode():
    incident = {"labels": {"root_cause_code": "DN_HEARTBEAT"}}
    rows = [_row("a", "Lost DataNode 10.0.0.1"), _row("b", "normal")]
    assert gold_ids(incident, rows) == ["a"]


# 方法说明：验证 token 预算和堆栈去重。
def test_select_log_rows_dedupes_stack_and_caps_tokens():
    rows = [{"log_id": "signal", "level": "ERROR",
             "redacted_message": "No space left on device", "component": "DataNode"}]
    rows += [{"log_id": f"stack-{index}", "level": "INFO",
              "redacted_message": f"    at org.apache.hadoop.Storage.frame{index}",
              "component": "DataNode"} for index in range(20)]
    selected = select_log_rows(rows, 50, token_budget=100)
    assert selected[0]["log_id"] == "signal"
    assert sum(1 for row in selected if "at org.apache" in row["redacted_message"]) == 1
    assert evidence_sufficiency(selected)["sufficient"] is True


# 方法说明：验证只有普通 INFO 时证据不足。
def test_evidence_sufficiency_flags_missing_signal():
    rows = [{"log_id": "a", "level": "INFO", "redacted_message": "started"}]
    assert evidence_sufficiency(rows)["sufficient"] is False


# 方法说明：验证无强信号时卷相关行作为兜底证据。
def test_volume_fallback_uses_volume_terms():
    incident = {"labels": {"root_cause_code": "DN_VOLUME"}}
    rows = [_row("a", "Adding replicas on volume /data"),
            _row("b", "unrelated")]
    assert gold_ids(incident, rows) == ["a"]
