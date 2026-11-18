"""对会话打分并做异常门禁，只有 PASS 才创建事件。"""

from __future__ import annotations

# SEVERITY 是日志级别对应的基础分数。
SEVERITY = {"FATAL": 1.0, "ERROR": 0.9, "WARN": 0.6, "INFO": 0.1, "DEBUG": 0.05}

# KEYWORDS 是故障相关关键词。
KEYWORDS = (
    "exception", "failed", "failure", "no space", "disk", "volume",
    "lost", "dead", "heartbeat", "safe mode", "safemode", "timeout",
    "refused", "unavailable", "corrupt", "error",
)


# score_rows 根据级别与关键词给会话打分。
def score_rows(rows):
    base = 0.0
    hits = 0
    for row in rows:
        base = max(base, SEVERITY.get((row.get("level") or "").upper(), 0.05))
        message = (row.get("redacted_message") or row.get("message") or "").lower()
        hits += sum(1 for word in KEYWORDS if word in message)
    if hits:
        base = max(base, min(1.0, 0.6 + 0.05 * hits))
    return round(min(1.0, base), 4)


# gate_session 返回 PASS/REJECT 与原因。
def gate_session(rows, threshold=0.6, min_lines=1):
    score = score_rows(rows)
    if len(rows) < int(min_lines):
        return {"decision": "REJECT", "score": score, "reason": "too_few_lines"}
    if score < float(threshold):
        return {"decision": "REJECT", "score": score, "reason": "below_threshold"}
    return {"decision": "PASS", "score": score, "reason": "score>=threshold"}


# build_event 把 PASS 会话转换为事件字典。
def build_event(event_id, batch_id, session_id, rows, score, threshold,
                host_alias="lab", start=None, end=None, detected_at=None):
    return {
        "event_id": event_id, "batch_id": batch_id, "host_alias": host_alias,
        "start_time": start, "end_time": end, "detected_at": detected_at,
        "max_anomaly_score": score, "threshold": threshold, "session_count": 1,
        "status": "ANOMALY_DETECTED", "session_id": session_id,
    }
