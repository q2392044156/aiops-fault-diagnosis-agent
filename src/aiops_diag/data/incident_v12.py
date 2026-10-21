"""Validation and lifecycle management for authorized v1.2 incidents."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from aiops_diag.data.common import key
from aiops_diag.data.v12_contracts import IncidentRecordV1


def load_incident(path: str | Path) -> IncidentRecordV1:
    return IncidentRecordV1.model_validate_json(Path(path).read_text(encoding="utf-8"))


def metric_eligibility(record: IncidentRecordV1) -> dict:
    root_reasons = []
    labels = record.labels
    if not labels.root_cause_code:
        root_reasons.append("root_cause_missing")
    if labels.confidence not in {"confirmed", "high"}:
        root_reasons.append("root_cause_not_confirmed")
    if labels.review_status not in {"reviewed", "adjudicated"}:
        root_reasons.append("independent_review_incomplete")
    if not labels.reviewer_id:
        root_reasons.append("reviewer_missing")
    if not labels.evidence_refs:
        root_reasons.append("label_evidence_missing")

    mttd_reasons = []
    stamps = record.timestamps
    if stamps.fault_start is None:
        mttd_reasons.append("fault_start_missing")
    if stamps.agent_detected is None:
        mttd_reasons.append("agent_detected_missing")
    if not stamps.timezone_source:
        mttd_reasons.append("timezone_source_missing")
    seconds = None
    if stamps.fault_start is not None and stamps.agent_detected is not None:
        seconds = (stamps.agent_detected - stamps.fault_start).total_seconds()
        if seconds < 0:
            mttd_reasons.append("negative_detection_delay")
            seconds = None
    return {
        "schema_version": 1,
        "incident_id": record.incident_id,
        "root_cause_metrics": {
            "eligible": not root_reasons,
            "value": "AVAILABLE" if not root_reasons else "N/A",
            "reason_codes": root_reasons,
        },
        "mttd": {
            "eligible": not mttd_reasons,
            "value_seconds": seconds if not mttd_reasons else "N/A",
            "reason_codes": mttd_reasons,
        },
    }


def validate_incident(record: IncidentRecordV1, *, at: datetime | None = None) -> dict:
    at = at or datetime.now(timezone.utc)
    if record.authorization.approved_at > at:
        raise ValueError("Incident authorization is not active yet")
    if record.authorization.retention_until <= at:
        raise ValueError("Incident authorization has expired")
    cutoff = record.diagnosis_snapshot.cutoff_time
    for item in [*record.diagnosis_snapshot.log_refs,
                 *record.diagnosis_snapshot.metric_refs,
                 *record.diagnosis_snapshot.ticket_refs]:
        if item.observed_at is not None and item.observed_at > cutoff:
            raise ValueError(f"Post-cutoff evidence is present: {item.ref_id}")
    return {
        "schema_version": 1,
        "incident_id": record.incident_id,
        "record_hash": key(record.model_dump(mode="json")),
        "authorization_active": True,
        "post_cutoff_evidence": 0,
        "metric_eligibility": metric_eligibility(record),
    }


def import_incident(database, path: str | Path) -> dict:
    record = load_incident(path)
    validation = validate_incident(record)
    payload = record.model_dump(mode="json")
    stamp = datetime.now(timezone.utc).isoformat()
    with database.transaction() as db:
        prior = db.execute("SELECT record_hash,status FROM incident_registry WHERE incident_id=?",
                           (record.incident_id,)).fetchone()
        if prior:
            if prior["record_hash"] != validation["record_hash"]:
                raise ValueError("Incident ID already exists with different content")
            return {**validation, "deduplicated": True, "status": prior["status"]}
        db.execute(
            "INSERT INTO incident_registry(incident_id,record_hash,record_json,authorization_id,"
            "retention_until,status,imported_at) VALUES (?,?,?,?,?,?,?)",
            (record.incident_id, validation["record_hash"],
             json.dumps(payload, ensure_ascii=False, sort_keys=True),
             record.authorization.authorization_id,
             record.authorization.retention_until.isoformat(), "ACTIVE", stamp),
        )
    return {**validation, "deduplicated": False, "status": "ACTIVE"}


def audit_incident(database, incident_id: str) -> dict:
    row = database.one("SELECT * FROM incident_registry WHERE incident_id=?", (incident_id,))
    if not row:
        raise FileNotFoundError("Incident was not found")
    value = {name: row[name] for name in (
        "incident_id", "record_hash", "authorization_id", "retention_until", "status",
        "imported_at", "deleted_at", "deletion_reason")}
    value["content_retained"] = row["record_json"] != "{}"
    return {"schema_version": 1, **value}


def delete_incident(database, incident_id: str, reason: str) -> dict:
    if not reason.strip():
        raise ValueError("Deletion reason is required")
    stamp = datetime.now(timezone.utc).isoformat()
    with database.transaction() as db:
        row = db.execute("SELECT status FROM incident_registry WHERE incident_id=?",
                         (incident_id,)).fetchone()
        if not row:
            raise FileNotFoundError("Incident was not found")
        if row["status"] != "DELETED":
            db.execute(
                "UPDATE incident_registry SET record_json='{}',status='DELETED',deleted_at=?,"
                "deletion_reason=? WHERE incident_id=?",
                (stamp, reason[:500], incident_id),
            )
            patterns = (f"%:{incident_id}:%", f"%:{incident_id}")
            for pattern in patterns:
                threads = db.execute(
                    "SELECT DISTINCT thread_id FROM langgraph_checkpoints WHERE thread_id LIKE ?",
                    (pattern,)).fetchall()
                for thread in threads:
                    db.execute("DELETE FROM langgraph_writes WHERE thread_id=?",
                               (thread["thread_id"],))
                    db.execute("DELETE FROM langgraph_checkpoints WHERE thread_id=?",
                               (thread["thread_id"],))
    return {"schema_version": 1, "incident_id": incident_id, "status": "DELETED",
            "deleted_at": stamp, "content_retained": False}
