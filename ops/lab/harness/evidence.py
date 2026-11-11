"""模块说明：定义证据级评测的关键证据规则。"""

from __future__ import annotations

import re

# 变量说明：GOLD_PATTERNS 是按故障族定义的关键证据模式。
GOLD_PATTERNS = {
    "DN_VOLUME": (
        r"no space left", r"diskoutofspace", r"failed volume", r"volume failed",
        r"too many failed volumes", r"read-only file system", r"diskchecker",
        r"failed to add storage directory", r"dysfunctional volume",
    ),
    "DN_HEARTBEAT": (
        r"lost heartbeat", r"lost datanode", r"dead datanode", r"removedead",
        r"heartbeat", r"exiting datanode",
    ),
    "NN_SAFE_MODE": (
        r"safe mode", r"safemode", r" safemodeexception",
    ),
    "NETWORK_CONNECTIVITY": (
        r"connection timed out", r"no route to host", r"network is unreachable",
        r"connection reset", r"retrying connect", r"connection refused",
    ),
    "DISK_IO": (
        r"read-only file system", r"input/output error", r"too many failed volumes",
        r"failed to add storage directory", r"diskchecker",
    ),
}


# 方法说明：gold_ids 返回案例中应被证据选择保留的关键行 ID。
def gold_ids(incident, rows):
    code = incident.get("labels", {}).get("root_cause_code")
    patterns = GOLD_PATTERNS.get(code, ())
    matched = []
    for row in rows:
        message = (row.get("message") or row.get("redacted_message") or "").lower()
        if any(re.search(pattern, message) for pattern in patterns):
            matched.append(row["log_id"])
    if not matched:
        for row in rows:
            message = (row.get("message") or row.get("redacted_message") or "").lower()
            level = (row.get("level") or "").upper()
            if (level in ("ERROR", "FATAL")
                    or any(term in message for term in ("volume", "disk", "storage"))):
                matched.append(row["log_id"])
    return sorted(set(matched))
