"""Freeze real, redacted HDFS event inputs for v1.1 report stability testing."""

import json
import os
import shutil
import sqlite3
import uuid
from pathlib import Path

from aiops_diag.agent.tools import AgentTools, document_evidence, log_evidence
from aiops_diag.data.common import digest, save
from aiops_diag.service.config import load as load_service
from aiops_diag.service.runtime import ServiceRuntime


class ReadOnlyDatabase:
    def __init__(self, path):
        self.path = Path(path).resolve()

    def _connect(self):
        db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        return db

    def one(self, sql, params=()):
        with self._connect() as db:
            row = db.execute(sql, params).fetchone()
            return dict(row) if row else None

    def all(self, sql, params=()):
        with self._connect() as db:
            return [dict(row) for row in db.execute(sql, params)]


def _spaced_ids(db, count):
    rows = db.all("SELECT event_id FROM events ORDER BY start_time,event_id")
    if count < 1 or len(rows) < count:
        raise ValueError("Not enough frozen events for report fixtures")
    return [rows[round(index * (len(rows) - 1) / (count - 1))]["event_id"]
            for index in range(count)] if count > 1 else [rows[0]["event_id"]]


def build(service_config_path, source_database_path, output_dir, count=40):
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError("Report fixture directory already exists")
    cfg = load_service(service_config_path)
    if cfg.get("agent_backend") != "v11_candidate":
        raise ValueError("Report fixtures require the opt-in v1.1 candidate")
    runtime = ServiceRuntime(cfg, role="worker")
    try:
        if runtime.ready_error:
            raise RuntimeError(runtime.ready_error)
        db = ReadOnlyDatabase(source_database_path)
        tools = AgentTools(db, cfg["agent"], runtime.retriever, runtime.manifest)
        cases = []
        for event_id in _spaced_ids(db, count):
            detected = tools.detect_anomaly(event_id)
            if not detected["ok"]:
                raise ValueError(f"Frozen event disappeared: {event_id}")
            event = detected["data"]["event"]
            logs = tools.query_logs(event_id, cfg["agent"]["tools"]["query_logs_limit"])
            if not logs["ok"]:
                raise ValueError(f"Frozen logs unavailable: {event_id}")
            log_rows = logs["data"]["items"]
            log_items = [log_evidence(row, runtime.manifest["release_id"])
                         for row in log_rows]
            components = sorted({row.get("component") for row in log_rows
                                 if row.get("component")})
            query = "HDFS异常事件只读排查 " + " ".join(components[:5])
            found = tools.retrieve_runbook(
                query, components[0] if len(components) == 1 else None, None,
                cfg["agent"]["tools"]["runbook_top_k"])
            doc_rows = found.get("data", {}).get("items", []) if found["ok"] else []
            doc_items = [document_evidence(row, runtime.retriever.manifest["kb_release_id"])
                         for row in doc_rows]
            ranked = tools.rank_root_causes(log_items, doc_items, components)
            evidence = [*log_items, *doc_items]
            cases.append({"case_id": event_id, "event": {name: event.get(name) for name in (
                "event_id", "start_time", "end_time", "max_anomaly_score", "threshold")},
                "hypotheses": ranked["data"]["hypotheses"],
                "evidence": evidence,
                "has_log_and_doc": bool(log_items and doc_items),
                "log_count": logs["data"].get("total", 0),
                "returned_doc_count": len(doc_items)})
        batch_ids = sorted({db.one("SELECT batch_id FROM events WHERE event_id=?",
                                   (row["case_id"],))["batch_id"] for row in cases})
        artifact_hashes = {}
        for batch_id in batch_ids:
            batch = db.one("SELECT artifact_dir FROM batches WHERE batch_id=?", (batch_id,))
            artifact_hashes[batch_id] = digest(Path(batch["artifact_dir"]) / "logs.parquet")
        manifest = {"schema_version": 1, "status": "REPORT_STABILITY_FIXTURES_ONLY",
                    "source": "redacted_public_hdfs_events",
                    "source_database_sha256": digest(source_database_path),
                    "source_artifact_hashes": artifact_hashes,
                    "candidate_release_id": runtime.agent_release["release_id"],
                    "model_release_id": runtime.manifest["release_id"],
                    "kb_release_id": runtime.retriever.manifest["kb_release_id"],
                    "count": len(cases),
                    "with_log_and_doc": sum(row["has_log_and_doc"] for row in cases),
                    "without_log_or_doc": sum(not row["has_log_and_doc"] for row in cases)}
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        staging = output_dir.parent / f".{output_dir.name}.{uuid.uuid4().hex}.partial"
        try:
            staging.mkdir()
            path = staging / "cases.jsonl"
            path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n"
                                    for row in cases), encoding="utf-8")
            manifest["cases_sha256"] = digest(path)
            save(staging / "manifest.json", manifest)
            os.replace(staging, output_dir)
        finally:
            if staging.exists() and staging.resolve().parent == output_dir.parent.resolve():
                shutil.rmtree(staging)
        return manifest
    finally:
        runtime.stop()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service_config", type=Path)
    parser.add_argument("source_database", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--count", type=int, default=40)
    args = parser.parse_args()
    result = build(args.service_config, args.source_database, args.output_dir,
                   args.count)
    print(json.dumps(result, ensure_ascii=False))
