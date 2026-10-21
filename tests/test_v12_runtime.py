import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from aiops_diag.data.incident_v12 import (audit_incident, delete_incident,
                                          import_incident, metric_eligibility,
                                          validate_incident)
from aiops_diag.data.v12_contracts import (DiagnosticSnapshotV12,
                                            IncidentRecordV1)
from aiops_diag.data.v12_import import import_snapshots
from aiops_diag.framework_v12.checkpoint import DatabaseCheckpointSaver
from aiops_diag.service.db import Database


def _jsonl(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _trace_snapshot():
    summary = {"task_count": 1, "report_count": 2, "edge_count": 1,
               "operation_count": 3, "operation_type_count": 1,
               "failed_event_count": 1, "component_counts": {"DataNode": 2},
               "top_operations": {"readBlock": 3}}
    base = {"schema_version": 1, "adapter_version": "v12_open_data_v1",
            "event_id": "evt_ext_tracebench_test", "dataset": "hdfs_v3_tracebench",
            "source_type": "public_dataset", "cluster_alias": "cluster_public",
            "product_version": None, "components": ["DataNode"],
            "observation_window": {"start": "2026-01-01T00:00:00+00:00",
                                   "end": "2026-01-01T00:01:00+00:00"},
            "log_templates": [], "trace_summary": summary, "signals": [],
            "evidence_refs": [{"ref_id": "sha256:" + "a" * 64,
                               "content_sha256": "a" * 64,
                               "relative_path": "trace.csv", "bytes": 1,
                               "redaction_status": "not_exported", "observed_at": None}]}
    from aiops_diag.data.v12_external import canonical_hash
    base["snapshot_hash"] = canonical_hash(base)
    return DiagnosticSnapshotV12.model_validate(base).model_dump(mode="json")


def _label():
    return {"schema_version": 1, "event_id": "evt_ext_tracebench_test",
            "dataset": "hdfs_v3_tracebench", "group_id": "g1", "split": "development",
            "anomaly_label": "anomaly", "injection_label": "test_injection",
            "root_cause_label": None, "metric_eligibility": {
                "public_injection_benchmark": True,
                "production_root_cause_ranking": False, "mttd": False,
                "reasons": ["root_cause_not_independently_confirmed"]}}


def test_external_snapshot_import_is_idempotent_and_keeps_labels_out(tmp_path):
    db = Database(tmp_path / "service.sqlite3")
    db.init()
    snapshots = tmp_path / "snapshots.jsonl"
    labels = tmp_path / "labels.jsonl"
    _jsonl(snapshots, [_trace_snapshot()])
    _jsonl(labels, [_label()])
    first = import_snapshots(db, snapshots, labels, "development", tmp_path / "artifacts")
    second = import_snapshots(db, snapshots, labels, "development", tmp_path / "artifacts")
    assert first["imported"] == 1
    assert second["deduplicated"] == 1
    metadata = db.get_event_metadata("evt_ext_tracebench_test")
    assert metadata["dataset"] == "hdfs_v3_tracebench"
    assert "injection_label" not in metadata
    stored = db.one("SELECT summary_json FROM event_trace_evidence WHERE event_id=?",
                    ("evt_ext_tracebench_test",))
    assert "test_injection" not in stored["summary_json"]


def test_database_checkpointer_survives_new_graph_instance(tmp_path):
    db = Database(tmp_path / "service.sqlite3")
    db.init()
    saver = DatabaseCheckpointSaver(db)

    def build():
        graph = StateGraph(dict)
        graph.add_node("step", lambda state: {**state, "count": state.get("count", 0) + 1})
        graph.add_edge(START, "step")
        graph.add_edge("step", END)
        return graph.compile(checkpointer=DatabaseCheckpointSaver(db))

    config = {"configurable": {"thread_id": "rel:dia:1", "checkpoint_ns": "agent-v12"}}
    assert build().invoke({"count": 0}, config)["count"] == 1
    assert build().invoke({"count": 10}, config)["count"] == 11
    assert saver.get_tuple(config) is not None
    assert db.one("SELECT COUNT(*) AS value FROM langgraph_checkpoints")["value"] >= 2


def _incident(now):
    cutoff = now - timedelta(minutes=2)
    return {"schema_version": 1, "incident_id": "inc_example_0001",
            "cluster_alias": "cluster_example", "product_version": "3.4.1",
            "fault_family": None,
            "authorization": {"authorization_id": "auth-1",
                              "approved_at": (now - timedelta(days=1)).isoformat(),
                              "retention_until": (now + timedelta(days=30)).isoformat(),
                              "deletion_contact": "data-owner"},
            "timestamps": {"fault_start": None, "first_observable_signal": None,
                           "agent_detected": None, "human_confirmed": None,
                           "recovered": None, "timezone_source": None},
            "diagnosis_snapshot": {"cutoff_time": cutoff.isoformat(),
                                   "log_refs": [], "metric_refs": [], "ticket_refs": []},
            "labels": {"root_cause_code": None, "confidence": "unknown",
                       "review_status": "draft", "evidence_refs": [],
                       "creator_id": "creator", "reviewer_id": None,
                       "adjudicator_id": None}}


def test_real_incident_lifecycle_keeps_unqualified_metrics_na(tmp_path):
    now = datetime.now(timezone.utc)
    value = _incident(now)
    record = IncidentRecordV1.model_validate(value)
    validation = validate_incident(record, at=now)
    assert validation["metric_eligibility"]["root_cause_metrics"]["value"] == "N/A"
    assert metric_eligibility(record)["mttd"]["value_seconds"] == "N/A"
    path = tmp_path / "incident.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    db = Database(tmp_path / "service.sqlite3")
    db.init()
    assert import_incident(db, path)["deduplicated"] is False
    assert import_incident(db, path)["deduplicated"] is True
    assert audit_incident(db, value["incident_id"])["content_retained"] is True
    deleted = delete_incident(db, value["incident_id"], "authorization withdrawn")
    assert deleted["content_retained"] is False
    assert audit_incident(db, value["incident_id"])["content_retained"] is False
