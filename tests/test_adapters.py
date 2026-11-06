"""模块说明：验证跨来源日志适配器与 canonical schema。"""

from pathlib import Path

import pytest

from aiops_diag.data.adapters import parse_line, parse_lines
from aiops_diag.data.canonical import CANONICAL_FIELDS, is_parsed

# 变量说明：ROOT 指向仓库根目录。
ROOT = Path(__file__).resolve().parents[1]


# 方法说明：验证 HDFS_v1 适配器字段映射。
def test_hdfs_v1_adapter_maps_fields():
    raw = (b"081109 203518 143 INFO dfs.DataNode$DataXceiver: "
           b"Receiving block blk_-1608999687919862906 src: /10.0.0.1:50010")
    row = parse_line("hdfs_v1", raw, 1, 0, "source")
    assert row["source_type"] == "hdfs_v1"
    assert row["component"] == "DataNode"
    assert row["logger"] == "dfs.DataNode$DataXceiver"
    assert row["pid"] == 143
    assert row["message"].startswith("Receiving block")
    assert row["session_ids"] == ["blk_-1608999687919862906"]
    assert row["parse_status"] == "ok"
    assert set(CANONICAL_FIELDS).issubset(row)


# 方法说明：验证容器日志适配器。
def test_container_adapter_parses_docker_and_wsl():
    raw = (b"[aiops-lab-dn1] 2026-10-28 12:59:49 INFO  FsDatasetImpl:425 - "
           b"Time taken to scan block pool")
    for source in ("docker_container", "wsl"):
        row = parse_line(source, raw, 1, 0, "source")
        assert row["source_type"] == source
        assert row["component"] == "DataNode"
        assert row["host_alias"] == "aiops-lab-dn1"
        assert row["logger"] == "FsDatasetImpl"
        assert row["level"] == "INFO"
        assert row["timestamp_utc"].endswith("+00:00")
        assert row["parse_status"] == "ok"


# 方法说明：验证续行保留原始消息。
def test_container_continuation_keeps_message():
    raw = b"    at org.apache.hadoop.util.DiskChecker.checkDirInternal"
    row = parse_line("docker_container", raw, 2, 0, "source",
                     fallback="2026-10-28T12:59:49+00:00")
    assert row["parse_status"] == "continuation"
    assert row["is_continuation"] is True
    assert "DiskChecker" in row["message"]
    assert row["timestamp_utc"] == "2026-10-28T12:59:49+00:00"
    assert is_parsed(row)


# 方法说明：验证缺失字段保持为空。
def test_missing_fields_are_null_not_fabricated():
    raw = b"[node1] 2026-10-28 12:59:49 INFO  Logger:1 - hello"
    row = parse_line("docker_container", raw, 1, 0, "source")
    assert row["pid"] is None
    assert row["session_ids"] == []


# 方法说明：验证未知来源被拒绝。
def test_unknown_source_type_rejected():
    with pytest.raises(ValueError, match="Unsupported source_type"):
        parse_line("unknown", b"x", 1, 0, "source")


# 方法说明：验证真实日志解析率达标。
def test_real_lab_logs_parse_rate():
    total = parsed = 0
    cases = [p for p in (ROOT / "ops/lab/wsl_cases").glob("*") if (p / "incident.json").is_file()]
    cases += [p for p in (ROOT / "ops/lab/real_batch_cases").glob("*") if (p / "incident.json").is_file()]
    assert len(cases) >= 140
    for case in cases:
        logs = list((case / "evidence/logs").glob("*.log"))
        if not logs:
            continue
        text = logs[0].read_text(encoding="utf-8", errors="replace")
        rows = parse_lines("docker_container", text.splitlines(), case.name,
                           "2026-10-28T00:00:00+00:00")
        total += len(rows)
        parsed += sum(1 for row in rows if is_parsed(row))
    assert total > 1000
    assert parsed / total >= 0.99
