"""验证 v12 runtime 相关功能、边界和回归行为。"""

import json
from datetime import UTC, datetime, timedelta

from langgraph.graph import END, START, StateGraph

from aiops_diag.platform.db import Database
from offline.case.contracts import IncidentRecordV1
from offline.case.incident import (
    audit_incident,
    delete_incident,
    import_incident,
    metric_eligibility,
    validate_incident,
)
from online.diagnosis.framework.checkpoint import DatabaseCheckpointSaver


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
    now = datetime.now(UTC)
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
