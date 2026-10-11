import hashlib
import json
import os
import shutil
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from aiops_diag.data.common import digest, key, save
from aiops_diag.data.parser import parse
from aiops_diag.modeling.templates import IP, content


LOG_SCHEMA = pa.schema([
    ("log_id", pa.string()), ("raw_line_no", pa.int64()), ("timestamp", pa.string()),
    ("level", pa.string()), ("component", pa.string()), ("redacted_message", pa.string()),
    ("template_id", pa.int32()), ("session_ids", pa.list_(pa.string())),
    ("parse_status", pa.string()),
])
QUARANTINE_SCHEMA = pa.schema([
    ("log_id", pa.string()), ("raw_line_no", pa.int64()), ("raw_hash", pa.string()),
    ("reason", pa.string()), ("redacted_preview", pa.string()),
])
LINK_SCHEMA = pa.schema([
    ("session_id", pa.string()), ("raw_line_no", pa.int64()), ("log_id", pa.string()),
])
SESSION_SCHEMA = pa.schema([
    ("session_id", pa.string()), ("template_ids", pa.list_(pa.int32())),
    ("start_time", pa.string()), ("end_time", pa.string()), ("line_count", pa.int32()),
    ("unknown_count", pa.int32()), ("first_log_id", pa.string()),
    ("last_log_id", pa.string()), ("host_alias", pa.string()),
])
PREDICTION_SCHEMA = pa.schema([
    ("session_id", pa.string()), ("start_time", pa.string()), ("end_time", pa.string()),
    ("line_count", pa.int32()), ("unknown_count", pa.int32()),
    ("anomaly_score", pa.float64()), ("threshold", pa.float64()),
    ("prediction", pa.int8()), ("first_log_id", pa.string()),
    ("last_log_id", pa.string()), ("host_alias", pa.string()),
])
EVENT_SCHEMA = pa.schema([
    ("event_id", pa.string()), ("host_alias", pa.string()), ("start_time", pa.string()),
    ("end_time", pa.string()), ("detected_at", pa.string()),
    ("max_anomaly_score", pa.float64()), ("threshold", pa.float64()),
    ("session_count", pa.int32()), ("status", pa.string()),
])
EVENT_MEMBER_SCHEMA = pa.schema([("event_id", pa.string()), ("session_id", pa.string())])


class BufferedWriter:
    def __init__(self, path, schema, batch_rows):
        self.path = Path(path)
        self.schema = schema
        self.batch_rows = batch_rows
        self.rows = []
        self.writer = pq.ParquetWriter(self.path, schema, compression="zstd")

    def add(self, row):
        self.rows.append(row)
        if len(self.rows) >= self.batch_rows:
            self.flush()

    def flush(self):
        if self.rows:
            self.writer.write_table(pa.Table.from_pylist(self.rows, schema=self.schema))
            self.rows.clear()

    def close(self):
        self.flush()
        self.writer.close()


def _raw_rows(path, source_hash, max_line_bytes):
    number = 0
    offset = 0
    with Path(path).open("rb") as handle:
        while True:
            raw = handle.readline(max_line_bytes + 1)
            if not raw:
                break
            number += 1
            start = offset
            offset += len(raw)
            if len(raw) > max_line_bytes and not raw.endswith(b"\n"):
                hasher = hashlib.sha256(raw)
                total = len(raw)
                while True:
                    extra = handle.readline(max_line_bytes + 1)
                    if not extra:
                        break
                    total += len(extra)
                    offset += len(extra)
                    hasher.update(extra)
                    if extra.endswith(b"\n"):
                        break
                yield {
                    "log_id": f"{source_hash}:{number}", "raw_line_no": number,
                    "byte_offset": start, "byte_length": total, "raw_hash": hasher.hexdigest(),
                    "timestamp_local": None, "level": None, "component": None, "message": None,
                    "session_ids": [], "parse_status": "line_too_long",
                }
                continue
            yield parse(raw, number, start, source_hash)


def _parquet_rows(path):
    columns = ["log_id", "raw_line_no", "raw_hash", "timestamp_local", "level",
               "component", "message", "session_ids", "parse_status"]
    for batch in pq.ParquetFile(path).iter_batches(columns=columns, batch_size=50000):
        yield from batch.to_pylist()


def _host_alias(source_hash, message):
    found = IP.search(message or "")
    if not found:
        return None
    return hashlib.sha256((source_hash + "|" + found.group(0)).encode()).hexdigest()[:16]


def _stage_db(path):
    db = sqlite3.connect(path)
    db.execute("PRAGMA journal_mode=OFF")
    db.execute("PRAGMA synchronous=OFF")
    db.execute("CREATE TABLE session_events(session_id TEXT,line_no INTEGER,log_id TEXT,"
               "stamp TEXT,level TEXT,template_id INTEGER,host_alias TEXT)")
    db.execute("CREATE INDEX idx_session_events ON session_events(session_id,line_no)")
    return db


def _session_rows(stage_db):
    cursor = stage_db.execute(
        "SELECT session_id,line_no,log_id,stamp,level,template_id,host_alias "
        "FROM session_events ORDER BY session_id,line_no"
    )
    current = None
    state = None
    for row in cursor:
        block = row[0]
        if block != current:
            if state:
                yield state
            current = block
            state = {
                "session_id": block, "template_ids": [], "start_time": None,
                "end_time": None, "line_count": 0, "unknown_count": 0,
                "first_log_id": None, "last_log_id": None, "host_alias": row[6],
            }
        stamp = row[3]
        state["template_ids"].append(int(row[5]))
        state["line_count"] += 1
        state["unknown_count"] += int(row[5] == 0)
        state["start_time"] = min(state["start_time"] or stamp, stamp)
        state["end_time"] = max(state["end_time"] or stamp, stamp)
        state["first_log_id"] = state["first_log_id"] or row[2]
        state["last_log_id"] = row[2]
    if state:
        yield state


def _score_sessions(stage_db, directory, model, cfg):
    session_writer = BufferedWriter(directory / "sessions.parquet", SESSION_SCHEMA,
                                    cfg["processing"]["parquet_batch_rows"])
    prediction_writer = BufferedWriter(directory / "predictions.parquet", PREDICTION_SCHEMA,
                                       cfg["processing"]["parquet_batch_rows"])
    pending = []
    count = anomalies = 0

    def flush():
        nonlocal count, anomalies
        if not pending:
            return
        scores, predictions = model.score([row["template_ids"] for row in pending])
        for index, row in enumerate(pending):
            session_writer.add(row)
            prediction = int(predictions[index])
            prediction_writer.add({
                "session_id": row["session_id"], "start_time": row["start_time"],
                "end_time": row["end_time"], "line_count": row["line_count"],
                "unknown_count": row["unknown_count"], "anomaly_score": float(scores[index]),
                "threshold": model.threshold, "prediction": prediction,
                "first_log_id": row["first_log_id"], "last_log_id": row["last_log_id"],
                "host_alias": row["host_alias"],
            })
            count += 1
            anomalies += prediction
        pending.clear()

    for session in _session_rows(stage_db):
        pending.append(session)
        if len(pending) >= cfg["processing"]["inference_batch_sessions"]:
            flush()
    flush()
    session_writer.close()
    prediction_writer.close()
    return count, anomalies


def _event_groups(predictions, max_gap, max_span):
    by_host = defaultdict(list)
    groups = []
    for row in predictions:
        if not row["prediction"]:
            continue
        if row["host_alias"] is None:
            groups.append([row])
        else:
            by_host[row["host_alias"]].append(row)
    gap = timedelta(seconds=max_gap)
    span = timedelta(seconds=max_span)
    for values in by_host.values():
        values.sort(key=lambda row: (row["start_time"], row["session_id"]))
        current = []
        first = previous = None
        for row in values:
            stamp = datetime.fromisoformat(row["start_time"])
            if not current or (stamp - previous <= gap and stamp - first <= span):
                current.append(row)
            else:
                groups.append(current)
                current = [row]
                first = stamp
            if first is None:
                first = stamp
            previous = stamp
        if current:
            groups.append(current)
    return groups


def _write_events(directory, batch_id, cfg):
    predictions = []
    for batch in pq.ParquetFile(directory / "predictions.parquet").iter_batches(batch_size=50000):
        predictions.extend(row for row in batch.to_pylist() if row["prediction"] == 1)
    groups = _event_groups(predictions, cfg["processing"]["event_max_gap_seconds"],
                           cfg["processing"]["event_max_span_seconds"])
    detected = datetime.now(timezone.utc).isoformat()
    events = []
    members = []
    for group in groups:
        member_ids = sorted(row["session_id"] for row in group)
        event_id = "evt_" + key([batch_id, member_ids])[:24]
        events.append({
            "event_id": event_id, "host_alias": group[0]["host_alias"],
            "start_time": min(row["start_time"] for row in group),
            "end_time": max(row["end_time"] for row in group), "detected_at": detected,
            "max_anomaly_score": max(row["anomaly_score"] for row in group),
            "threshold": group[0]["threshold"], "session_count": len(group),
            "status": "ANOMALY_DETECTED",
        })
        members.extend({"event_id": event_id, "session_id": session_id}
                       for session_id in member_ids)
    pq.write_table(pa.Table.from_pylist(events, schema=EVENT_SCHEMA),
                   directory / "events.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist(members, schema=EVENT_MEMBER_SCHEMA),
                   directory / "event_sessions.parquet", compression="zstd")
    return len(events)


def process(task, cfg, model, set_stage):
    runtime = Path(cfg["paths"]["runtime_dir"])
    staging_root = runtime / "staging"
    batches_root = runtime / "batches"
    staging_root.mkdir(parents=True, exist_ok=True)
    batches_root.mkdir(parents=True, exist_ok=True)
    stage = staging_root / task["task_id"]
    final = batches_root / task["batch_id"]
    if final.exists():
        manifest = json.loads((final / "manifest.json").read_text(encoding="utf-8"))
        expected = {"batch_id": task["batch_id"], "input_hash": task["input_hash"],
                    "release_id": model.manifest["release_id"],
                    "processing_hash": cfg["processing_hash"]}
        if any(manifest.get(name) != value for name, value in expected.items()):
            raise ValueError("Existing completed batch belongs to different inputs")
        for name, expected in manifest["artifacts"].items():
            if digest(final / name) != expected:
                raise ValueError("Existing completed batch artifact changed")
        return final, manifest
    if stage.exists():
        if stage.resolve().parent != staging_root.resolve():
            raise ValueError("Invalid staging directory")
        shutil.rmtree(stage)
    stage.mkdir()
    set_stage("PARSING")
    source_hash = task["input_hash"]
    source_path = Path(task["source_ref"])
    if task["source_kind"] == "upload":
        rows = _raw_rows(source_path, source_hash, cfg["processing"]["max_line_bytes"])
    elif task["source_kind"] == "registered":
        rows = _parquet_rows(source_path)
    else:
        raise ValueError("Unsupported source kind")
    batch_rows = cfg["processing"]["parquet_batch_rows"]
    logs = BufferedWriter(stage / "logs.parquet", LOG_SCHEMA, batch_rows)
    quarantine = BufferedWriter(stage / "quarantine.parquet", QUARANTINE_SCHEMA, batch_rows)
    links = BufferedWriter(stage / "links.parquet", LINK_SCHEMA, batch_rows)
    temp_db = _stage_db(stage / "session_events.sqlite3")
    pending_events = []
    total = parsed = quarantined = 0
    writers_closed = False
    try:
        for row in rows:
            total += 1
            valid = row.get("parse_status") == "ok" and row.get("timestamp_local") and row.get("session_ids")
            template_id = model.template(row) if valid else None
            redacted = content(row) if row.get("message") is not None else ""
            logs.add({
                "log_id": row["log_id"], "raw_line_no": row["raw_line_no"],
                "timestamp": row.get("timestamp_local"), "level": row.get("level"),
                "component": row.get("component"), "redacted_message": redacted,
                "template_id": template_id, "session_ids": row.get("session_ids") or [],
                "parse_status": row.get("parse_status", "format_error"),
            })
            if not valid:
                reason = row.get("parse_status", "format_error")
                if reason == "ok" and not row.get("session_ids"):
                    reason = "no_block"
                quarantine.add({
                    "log_id": row["log_id"], "raw_line_no": row["raw_line_no"],
                    "raw_hash": row.get("raw_hash", ""), "reason": reason,
                    "redacted_preview": redacted[:500],
                })
                quarantined += 1
                continue
            parsed += 1
            alias = _host_alias(source_hash, row.get("message"))
            for block in sorted(set(row["session_ids"])):
                links.add({"session_id": block, "raw_line_no": row["raw_line_no"],
                           "log_id": row["log_id"]})
                pending_events.append((block, row["raw_line_no"], row["log_id"],
                                       row["timestamp_local"], row.get("level"), template_id, alias))
                if len(pending_events) >= batch_rows:
                    temp_db.executemany("INSERT INTO session_events VALUES (?,?,?,?,?,?,?)", pending_events)
                    temp_db.commit()
                    pending_events.clear()
        if pending_events:
            temp_db.executemany("INSERT INTO session_events VALUES (?,?,?,?,?,?,?)", pending_events)
            temp_db.commit()
        logs.close(); quarantine.close(); links.close()
        writers_closed = True
        set_stage("SCORING")
        session_count, anomaly_count = _score_sessions(temp_db, stage, model, cfg)
        model.assert_unchanged()
    finally:
        if not writers_closed:
            for writer in (logs, quarantine, links):
                try:
                    writer.close()
                except Exception:
                    pass
        temp_db.close()
    (stage / "session_events.sqlite3").unlink(missing_ok=True)
    set_stage("AGGREGATING")
    event_count = _write_events(stage, task["batch_id"], cfg)
    names = ["logs.parquet", "quarantine.parquet", "links.parquet", "sessions.parquet",
             "predictions.parquet", "events.parquet", "event_sessions.parquet"]
    counts = {"total_lines": total, "parsed_lines": parsed,
              "quarantined_lines": quarantined, "session_count": session_count,
              "anomaly_count": anomaly_count, "event_count": event_count}
    manifest = {
        "schema_version": 1, "batch_id": task["batch_id"], "task_id": task["task_id"],
        "input_hash": source_hash, "release_id": model.manifest["release_id"],
        "release_manifest_hash": digest(Path(cfg["release_dir"]) / "service_release.json"),
        "processing_hash": cfg["processing_hash"], "counts": counts,
        "artifacts": {name: digest(stage / name) for name in names},
    }
    save(stage / "manifest.json", manifest)
    os.replace(stage, final)
    return final, manifest


def parquet_rows(path, batch_size=50000):
    for batch in pq.ParquetFile(path).iter_batches(batch_size=batch_size):
        yield from batch.to_pylist()


def database_payload(directory, manifest):
    directory = Path(directory)
    artifacts = {name: {"relative_path": name, "sha256": value}
                 for name, value in manifest["artifacts"].items()}
    return (
        manifest["counts"], parquet_rows(directory / "predictions.parquet"),
        parquet_rows(directory / "events.parquet"),
        parquet_rows(directory / "event_sessions.parquet"), artifacts,
    )
