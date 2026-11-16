"""模块说明：验证可解释根因信号与滑动窗口事件合并。"""

from aiops_diag.diagnosis.evidence import EvidenceSelector
from aiops_diag.diagnosis.signals import analyze_rows
from aiops_diag.diagnosis.tools import AgentTools
from ops.lab.harness.ingest import _merge_passing


# 方法说明：构造带级别和组件的日志行。
def _row(log_id, message, level="WARN", component="DataNode"):
    return {"log_id": log_id, "redacted_message": message, "level": level,
            "component": component}


# 方法说明：验证心跳同义表述能被识别，而不是回退到卷故障。
def test_heartbeat_paraphrase_is_detected():
    rows = [_row("a", "DataNode prod-datanode-08 missed its liveness deadline"),
            _row("b", "BLOCK* schedule replication for prod-datanode-08", "INFO")]
    assert analyze_rows(rows)["codes"][0]["code"] == "DN_HEARTBEAT"


# 方法说明：验证卷故障干扰存在时，真实心跳信号仍按分数排序在前。
def test_heartbeat_signal_beats_volume_distractor():
    rows = [_row("a", "Volume /data/2 failed, 0 bytes available"),
            _row("b", "Slow volume detection", "INFO"),
            _row("c", "DataNode prod-datanode-08 missed its liveness deadline")]
    ranked = analyze_rows(rows)["codes"]
    assert ranked[0]["code"] == "DN_HEARTBEAT"
    assert [item["code"] for item in ranked] == ["DN_HEARTBEAT", "DN_VOLUME"]


# 方法说明：验证 WSL 卷故障的 “failed volumes” 写法仍被识别。
def test_wsl_failed_volumes_is_detected():
    rows = [_row("a", "DiskChecker$DiskErrorException: Too many failed volumes - "
                      "current valid volumes: 0", "ERROR"),
            _row("b", "Directory is not writable: /mnt/labvol", "WARN")]
    assert analyze_rows(rows)["codes"][0]["code"] == "DN_VOLUME"


# 方法说明：验证安全模式改写和“阈值”上下文可以组合成强信号。
def test_safe_mode_paraphrase_is_detected():
    rows = [_row("a", "Entering maintenance mode", "INFO", "NameNode"),
            _row("b", "Startup guard is active. The reported blocks needs additional "
                      "blocks to reach the threshold", "WARN", "NameNode")]
    top = analyze_rows(rows)["codes"][0]
    assert top["code"] == "NN_SAFE_MODE" and top["score"] >= 2.8


# 方法说明：验证网络故障与心跳故障同时出现时，连接重试信号优先。
def test_network_signal_beats_heartbeat_noise():
    rows = [_row("a", "Lost DataNode 10.0.0.1", "WARN", "NameNode"),
            _row("b", "Retrying connect to server: namenode:9000", "INFO")]
    assert analyze_rows(rows)["codes"][0]["code"] == "NETWORK_CONNECTIVITY"


# 方法说明：验证根因排序使用日志信号而不是固定故障优先级。
def test_rank_root_causes_follows_log_signal():
    cards = [{"evidence_id": "d1", "root_cause_code": "DN_HEARTBEAT",
              "title": "心跳丢失", "component": "NameNode"}]
    logs = [{"evidence_id": "l1", "source_ref": "a", "component": "NameNode",
             "level": "WARN",
             "excerpt_redacted": "Startup guard is active. The reported blocks "
                                 "needs additional blocks to reach the threshold"}]
    data = AgentTools.rank_root_causes(logs, cards, ["NameNode"])["data"]
    assert data["hypotheses"][0]["root_cause_code"] == "NN_SAFE_MODE"
    assert data["signal_scores"][0]["root_cause_code"] == "NN_SAFE_MODE"


# 方法说明：验证数字归一化后重复的普通日志只保留一条证据。
def test_evidence_dedupes_numeric_variants():
    rows = [_row(f"n{index}", f"normal workload line {index}", "INFO")
            for index in range(10)]
    rows.append(_row("err", "No space left on device", "ERROR"))
    selected, quality = EvidenceSelector(50, 2000, "DataNode").select(rows)
    assert sum(1 for row in selected if "normal workload" in row["redacted_message"]) == 1
    assert quality["has_signal"] is True


# 方法说明：构造一个 PASS 窗口及其门禁结果。
def _window(window_id, start, end, rows):
    window = {"window_id": window_id, "source_type": "docker_container",
              "component": "DataNode", "start": start, "end": end, "rows": rows}
    return window, {"score": 1.0, "reason": "error_present"}


# 方法说明：验证重叠窗口合并、行去重和事件边界。
def test_merge_passing_merges_overlapping_windows():
    passing = [
        _window("w1", "2026-10-28T11:20:00+00:00", 1793186460.0,
                [{"log_id": "a"}, {"log_id": "b"}]),
        _window("w2", "2026-10-28T11:20:10+00:00", 1793186520.0,
                [{"log_id": "b"}, {"log_id": "c"}]),
        _window("w3", "2026-10-28T11:20:20+00:00", 1793186580.0,
                [{"log_id": "c"}, {"log_id": "d"}]),
    ]
    merged = _merge_passing(passing, gap_seconds=0, max_span_seconds=300)
    assert len(merged) == 1
    assert merged[0]["window_ids"] == ["w1", "w2", "w3"]
    assert [row["log_id"] for row in merged[0]["rows"]] == ["a", "b", "c", "d"]


# 方法说明：验证超过最大跨度时拆成新事件。
def test_merge_passing_respects_max_span():
    passing = [
        _window("w1", "2026-10-28T11:20:00+00:00", 1793186460.0, [{"log_id": "a"}]),
        _window("w2", "2026-10-28T11:20:10+00:00", 1793186520.0, [{"log_id": "b"}]),
        _window("w3", "2026-10-28T11:20:20+00:00", 1793186580.0, [{"log_id": "c"}]),
    ]
    merged = _merge_passing(passing, gap_seconds=0, max_span_seconds=120)
    assert [window["window_ids"] for window in merged] == [["w1", "w2"], ["w3"]]
