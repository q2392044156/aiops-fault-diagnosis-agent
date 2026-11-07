"""模块说明：验证证据级评测的关键证据规则。"""

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


# 方法说明：验证无强信号时卷相关行作为兜底证据。
def test_volume_fallback_uses_volume_terms():
    incident = {"labels": {"root_cause_code": "DN_VOLUME"}}
    rows = [_row("a", "Adding replicas on volume /data"),
            _row("b", "unrelated")]
    assert gold_ids(incident, rows) == ["a"]
