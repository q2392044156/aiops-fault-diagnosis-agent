"""Idempotent import of label-free v1.2 diagnostic snapshots into the service."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pyarrow as pa
import pyarrow.parquet as pq

from aiops_diag.data.common import key
from aiops_diag.data.v12_contracts import DiagnosticSnapshotV12, EvaluationLabelV12
from aiops_diag.service.pipeline import LOG_SCHEMA


def _read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def _write_logs(path: Path, snapshots: Iterable[DiagnosticSnapshotV12]) -> int:
    rows = []
    for snapshot in snapshots:
        session_id = "ses_" + key(snapshot.event_id)[:24]
        for ordinal, item in enumerate(snapshot.log_templates, 1):
            rows.append({
                "log_id": item.log_id,
                "raw_line_no": ordinal,
                "timestamp": item.timestamp,
                "level": item.level,
                "component": item.component,
                "redacted_message": item.redacted_message,
                "template_id": int(item.template_id[-8:], 16) % 2147483647,
                "session_ids": [session_id],
                "parse_status": "external_safe_template",
            })
    table = pa.Table.from_pylist(rows, schema=LOG_SCHEMA) if rows else pa.Table.from_arrays(
        [pa.array([], type=field.type) for field in LOG_SCHEMA], schema=LOG_SCHEMA)
    pq.write_table(table, path, compression="zstd")
    return len(rows)


def import_snapshots(database, snapshots_path: str | Path, labels_path: str | Path,
                     split: str, artifact_root: str | Path) -> dict:
    snapshots_path = Path(snapshots_path)
    labels_path = Path(labels_path)
    snapshots = [DiagnosticSnapshotV12.model_validate(row)
                 for row in _read_jsonl(snapshots_path)]
    labels = [EvaluationLabelV12.model_validate(row) for row in _read_jsonl(labels_path)]
    selected_ids = {row.event_id for row in labels if row.split == split}
    selected = [row for row in snapshots if row.event_id in selected_ids]
    if len(selected) != len(selected_ids):
        missing = sorted(selected_ids - {row.event_id for row in selected})
        raise ValueError(f"Snapshots are missing for evaluation labels: {missing}")
    source_hash = key([row.snapshot_hash for row in selected])
    batch_id = "bat_ext_" + key([split, source_hash])[:20]
    artifact_dir = Path(artifact_root).resolve() / batch_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    logs_path = artifact_dir / "logs.parquet"
    log_count = _write_logs(logs_path, selected)
    stamp = datetime.now(timezone.utc).isoformat()
    imported = deduplicated = 0
    with database.transaction() as db:
        db.execute(
            "INSERT OR IGNORE INTO batches(batch_id,source_kind,source_ref,input_hash,release_id,"
            "processing_hash,status,artifact_dir,total_lines,parsed_lines,session_count,event_count,"
            "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (batch_id, "v12_external_snapshot", str(snapshots_path.resolve()), source_hash,
             "v1.2-public-data", "v12_external_import_v1", "SUCCEEDED", str(artifact_dir),
             log_count, log_count, len(selected), len(selected), stamp, stamp),
        )
        for snapshot in selected:
            prior = db.execute(
                "SELECT snapshot_hash FROM external_event_imports WHERE event_id=?",
                (snapshot.event_id,),
            ).fetchone()
            if prior:
                if prior["snapshot_hash"] != snapshot.snapshot_hash:
                    raise ValueError(f"External event content conflict: {snapshot.event_id}")
                deduplicated += 1
                continue
            session_id = "ses_" + key(snapshot.event_id)[:24]
            window = snapshot.observation_window
            db.execute(
                "INSERT INTO sessions(batch_id,session_id,start_time,end_time,line_count,"
                "unknown_count,anomaly_score,threshold,prediction,first_log_id,last_log_id,host_alias) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (batch_id, session_id, window.get("start"), window.get("end"),
                 sum(row.count for row in snapshot.log_templates), 0, 0.0, 1.0, 0,
                 snapshot.log_templates[0].log_id if snapshot.log_templates else None,
                 snapshot.log_templates[-1].log_id if snapshot.log_templates else None, None),
            )
            db.execute(
                "INSERT INTO events(event_id,batch_id,host_alias,start_time,end_time,detected_at,"
                "max_anomaly_score,threshold,session_count,status) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (snapshot.event_id, batch_id, None, window.get("start"), window.get("end"),
                 stamp, 0.0, 1.0, 1, "IMPORTED_PUBLIC_DATA"),
            )
            db.execute("INSERT INTO event_sessions VALUES (?,?,?)",
                       (snapshot.event_id, batch_id, session_id))
            metadata = {
                "source_type": snapshot.source_type,
                "dataset": snapshot.dataset,
                "split": split,
                "snapshot_hash": snapshot.snapshot_hash,
                "cluster_alias": snapshot.cluster_alias,
            }
            if snapshot.product_version:
                metadata["product_version"] = snapshot.product_version
            db.executemany(
                "INSERT INTO event_metadata(event_id,name,value) VALUES (?,?,?)",
                ((snapshot.event_id, name, value) for name, value in metadata.items()),
            )
            if snapshot.trace_summary:
                summary = snapshot.trace_summary.model_dump(mode="json")
                db.execute(
                    "INSERT INTO event_trace_evidence(event_id,summary_json,evidence_hash,"
                    "source_version,observed_at,observed_until) VALUES (?,?,?,?,?,?)",
                    (snapshot.event_id, json.dumps(summary, ensure_ascii=False, sort_keys=True),
                     key(summary), snapshot.adapter_version, window.get("start"), window.get("end")),
                )
            db.execute(
                "INSERT INTO external_event_imports(event_id,dataset,split,adapter_version,"
                "snapshot_hash,source_hash,imported_at) VALUES (?,?,?,?,?,?,?)",
                (snapshot.event_id, snapshot.dataset, split, snapshot.adapter_version,
                 snapshot.snapshot_hash, source_hash, stamp),
            )
            imported += 1
    return {"schema_version": 1, "batch_id": batch_id, "split": split,
            "selected": len(selected), "imported": imported,
            "deduplicated": deduplicated, "log_templates": log_count,
            "source_hash": source_hash}
