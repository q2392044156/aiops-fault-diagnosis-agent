"""模块说明：构造受控实验的 incident 记录与证据文件（路线 A）。"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from offline.ingestion.v12_contracts import IncidentRecordV1

# 变量说明：PATTERNS 是证据脱敏规则，顺序执行。
PATTERNS = (
    (re.compile(r"\bblk_-?\d+\b"), "<:BLOCK:>"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"), "<:IP:>"),
    (re.compile(r"(?<![A-Za-z0-9])/(?:[A-Za-z0-9._-]+/){2,}[A-Za-z0-9._-]+"), "<:PATH:>"),
    (re.compile(r"\b0x[0-9A-Fa-f]+\b"), "<:HEX:>"),
)


# 方法说明：redact 对日志做确定性脱敏，证据与报告使用同一份文本。
def redact(text):
    value = text or ""
    for pattern, replacement in PATTERNS:
        value = pattern.sub(replacement, value)
    return value


# 方法说明：sha256_text 计算文本的 SHA-256，用于证据引用。
def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# 方法说明：write_evidence 写出证据文件并返回可写入 incident 的引用。
def write_evidence(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return {"ref_id": path.stem, "content_sha256": sha256_text(text),
            "redaction_status": "approved_redacted",
            "observed_at": None}


# 方法说明：iso 把 datetime 规范为带时区的 ISO 字符串。
def iso(value):
    return value.astimezone(timezone.utc).isoformat()


# 方法说明：build_incident 组装并校验一条真实故障记录（MVP 阶段）。
def build_incident(*, incident_id, cluster_alias, fault_code, fault_family, timestamps,
                   log_ref, metric_ref, ticket_ref, cutoff_time,
                   product_version="3.3.6", creator_id="lab-harness",
                   reviewer_id="lab-reviewer", retention_days=30):
    now = datetime.now(timezone.utc)
    record = {
        "schema_version": 1,
        "incident_id": incident_id,
        "cluster_alias": cluster_alias,
        "product_version": product_version,
        "fault_family": fault_family,
        "authorization": {
            "authorization_id": "auth_lab_001",
            "approved_at": iso(now - timedelta(hours=1)),
            "retention_until": iso(now + timedelta(days=retention_days)),
            "deletion_contact": "lab@example.invalid",
        },
        "timestamps": {
            "fault_start": iso(timestamps["fault_start"]),
            "first_observable_signal": iso(timestamps["first_observable_signal"]),
            "agent_detected": iso(timestamps["agent_detected"]) if timestamps.get("agent_detected") else None,
            "human_confirmed": iso(timestamps["human_confirmed"]),
            "recovered": iso(timestamps["recovered"]),
            "timezone_source": "Asia/Shanghai (lab-ntp)",
        },
        "diagnosis_snapshot": {
            "cutoff_time": iso(cutoff_time),
            "log_refs": [{**log_ref, "observed_at": iso(cutoff_time)}],
            "metric_refs": [{**metric_ref, "observed_at": iso(cutoff_time)}],
            "ticket_refs": [{**ticket_ref, "observed_at": iso(cutoff_time)}],
        },
        "labels": {
            "root_cause_code": fault_code,
            "confidence": "confirmed",
            "review_status": "reviewed",
            "evidence_refs": [log_ref["ref_id"], metric_ref["ref_id"]],
            "creator_id": creator_id,
            "reviewer_id": reviewer_id,
            "adjudicator_id": None,
        },
    }
    return IncidentRecordV1.model_validate(record)


# 方法说明：write_incident 把校验后的记录写成 JSON 文件。
def write_incident(path, record):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record.model_dump(mode="json"), ensure_ascii=False,
                               indent=2) + "\n", encoding="utf-8")
    return path
