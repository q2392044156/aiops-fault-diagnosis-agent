"""模块说明：按来源解析日志，并输出统一的 canonical log。"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from .canonical import canonical_log
from .parser import BLOCK, parse as parse_hdfs

# 变量说明：CONTAINER 匹配 [host] timestamp LEVEL rest 的容器日志。
CONTAINER = re.compile(
    r"^\[(?P<host>[^\]]+)\]\s+(?P<stamp>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}"
    r"(?:[.,]\d+)?)\s+(?P<level>[A-Z]+)\s+(?P<rest>.*)$")
# 变量说明：REST 拆分 logger[:line] 与 message。
REST = re.compile(r"^(?P<logger>[A-Za-z0-9_$.]+)(?::(?P<line>\d+))?\s*(?:-|:)\s*(?P<message>.*)$")


# 方法说明：_component 把 logger 或 host 映射到统一组件。
def _component(value):
    text = (value or "").lower()
    if "namenode" in text or "fsnamesystem" in text:
        return "NameNode"
    if "journal" in text:
        return "JournalNode"
    if "datanode" in text or re.search(r"(^|[-_])dn\d*($|[-_])", text):
        return "DataNode"
    if "balancer" in text:
        return "Balancer"
    return value


# 方法说明：_timestamp 把容器日志时间统一到 UTC。
def _timestamp(stamp):
    normalized = stamp.replace(",", ".")
    try:
        value = datetime.fromisoformat(normalized)
    except ValueError:
        return None, None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat(), value.astimezone(timezone.utc).isoformat()


# 方法说明：parse_hdfs_v1 解析 HDFS_v1 行。
def parse_hdfs_v1(raw, number, offset, source_hash):
    row = parse_hdfs(raw, number, offset, source_hash)
    logger = row.get("component")
    return canonical_log(
        "hdfs_v1", log_id=row["log_id"], raw_line_no=number, byte_offset=offset,
        byte_length=row["byte_length"], raw_hash=row["raw_hash"],
        timestamp_original=row.get("timestamp_original"),
        timestamp_local=row.get("timestamp_local"), timestamp_utc=None,
        timezone_assumption="unknown", level=row.get("level"),
        component=_component(logger), logger=logger, pid=row.get("pid"),
        message=row.get("message"), session_ids=row.get("session_ids"),
        parse_status=row.get("parse_status"), parser_version="hdfs_v1@1")


# 方法说明：parse_container 解析 Docker/WSL 的 [host] 日志。
def parse_container(raw, number, offset, source_hash, fallback=None,
                    source_type="docker_container"):
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    text = text.rstrip("\r\n")
    raw_bytes = raw if isinstance(raw, bytes) else text.encode("utf-8")
    blocks = sorted(set(BLOCK.findall(text)))
    match = CONTAINER.match(text)
    if not match:
        return canonical_log(
            source_type, log_id=f"{source_hash}:{number}", raw_line_no=number,
            byte_offset=offset, byte_length=len(raw_bytes),
            raw_hash=__import__("hashlib").sha256(raw_bytes).hexdigest(),
            timestamp_utc=fallback, timezone_assumption="UTC", message=text,
            session_ids=blocks, parse_status="continuation",
            is_continuation=True, parser_version=f"{source_type}@1")
    host = match.group("host")
    stamp = match.group("stamp")
    local, utc = _timestamp(stamp)
    rest = match.group("rest")
    detail = REST.match(rest)
    logger = detail.group("logger") if detail else None
    message = detail.group("message") if detail else rest
    return canonical_log(
        source_type, log_id=f"{source_hash}:{number}", raw_line_no=number,
        byte_offset=offset, byte_length=len(raw_bytes),
        raw_hash=__import__("hashlib").sha256(raw_bytes).hexdigest(),
        timestamp_original=stamp, timestamp_local=local, timestamp_utc=utc,
        timezone_assumption="UTC", level=match.group("level"),
        component=_component(host), logger=logger, host_alias=host,
        message=message, session_ids=blocks,
        parse_status="ok" if local else "time_error",
        parser_version=f"{source_type}@1")


# 方法说明：parse_line 按来源分派单行解析。
def parse_line(source_type, raw, number, offset, source_hash, fallback=None):
    if source_type == "hdfs_v1":
        return parse_hdfs_v1(raw, number, offset, source_hash)
    if source_type in ("docker_container", "wsl"):
        return parse_container(raw, number, offset, source_hash, fallback, source_type)
    raise ValueError(f"Unsupported source_type: {source_type}")


# 方法说明：parse_lines 解析整份日志并累计字节偏移。
def parse_lines(source_type, lines, source_hash, fallback=None):
    rows, offset = [], 0
    for number, line in enumerate(lines, 1):
        raw = line.encode("utf-8") if isinstance(line, str) else line
        rows.append(parse_line(source_type, raw, number, offset, source_hash, fallback))
        offset += len(raw) + 1
    return rows
