"""模块说明：定义跨日志源的 canonical log 字段与规范化函数。"""

from __future__ import annotations

# 变量说明：CANONICAL_FIELDS 是跨来源日志的统一字段集合。
CANONICAL_FIELDS = (
    "log_id", "source_type", "source_file", "raw_line_no", "byte_offset",
    "byte_length", "raw_hash", "timestamp_original", "timestamp_local",
    "timestamp_utc", "timezone_assumption", "level", "component", "logger",
    "host_alias", "pid", "message", "session_ids", "parse_status",
    "parser_version", "is_continuation",
)


# 方法说明：canonical_log 把适配器输出补齐为统一字段。
def canonical_log(source_type, **fields):
    row = {name: fields.get(name) for name in CANONICAL_FIELDS}
    row["source_type"] = source_type
    row["session_ids"] = list(fields.get("session_ids") or [])
    row["parse_status"] = fields.get("parse_status") or "ok"
    row["parser_version"] = fields.get("parser_version") or f"{source_type}@1"
    row["timezone_assumption"] = fields.get("timezone_assumption") or "unknown"
    row["is_continuation"] = bool(fields.get("is_continuation", False))
    if row["pid"] is not None:
        try:
            row["pid"] = int(row["pid"])
        except (TypeError, ValueError):
            row["pid"] = None
    return row


# 方法说明：is_parsed 判断该行是否被适配器成功接收。
def is_parsed(row):
    return row.get("parse_status") in ("ok", "continuation")
