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


# keyword_hits 统计一条消息命中的故障关键词个数。
def keyword_hits(message):
    text = (message or "").lower()
    return sum(1 for word in KEYWORDS if word in text)


# combine 把「最高级别分」与「关键词命中数」合成为最终分数。
def combine(severity, hits):
    if hits:
        severity = max(severity, min(1.0, 0.6 + 0.05 * hits))
    return round(min(1.0, severity), 4)


# session_score 由级别序列与关键词命中总数计算 0~1 的规则分数。
def session_score(levels, hits):
    base = 0.0
    for level in levels:
        base = max(base, SEVERITY.get((level or "").upper(), 0.05))
    return combine(base, hits)


# score_rows 根据级别与关键词给会话打分。
def score_rows(rows):
    levels = [row.get("level") for row in rows]
    hits = sum(keyword_hits(row.get("redacted_message") or row.get("message")) for row in rows)
    return session_score(levels, hits)


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
