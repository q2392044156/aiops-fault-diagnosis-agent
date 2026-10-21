"""Read-only trace evidence for v1.2 framework diagnoses."""

from __future__ import annotations

import json
import time

from aiops_diag.agent.tools import result
from aiops_diag.agent_v11.tools import CandidateAgentTools
from aiops_diag.data.common import key


class V12AgentTools(CandidateAgentTools):
    def read_trace_summary(self, event_id):
        started = time.perf_counter()
        row = self.db.one(
            "SELECT * FROM event_trace_evidence WHERE event_id=?", (event_id,))
        if not row:
            return result({"status": "not_available", "item": None},
                          provenance={"event_id": event_id}, started=started)
        summary = json.loads(row["summary_json"])
        return result({"status": "available", "item": {
            "event_id": event_id,
            "summary": summary,
            "evidence_hash": row["evidence_hash"],
            "source_version": row["source_version"],
            "observed_at": row["observed_at"],
            "observed_until": row["observed_until"],
        }}, provenance={"event_id": event_id, "source": "event_trace_evidence"},
            started=started)


def trace_evidence(item):
    summary = item["summary"]
    component_counts = summary.get("component_counts", {})
    components = sorted(component_counts, key=lambda name: (-component_counts[name], name))
    facts = [
        f"tasks={summary.get('task_count', 0)}",
        f"reports={summary.get('report_count', 0)}",
        f"edges={summary.get('edge_count', 0)}",
        f"operations={summary.get('operation_count', 0)}",
        f"failed_events={summary.get('failed_event_count', 0)}",
    ]
    evidence_id = "evd_trace_" + key([item["event_id"], item["evidence_hash"]])[:20]
    return {
        "evidence_id": evidence_id,
        "kind": "trace",
        "source_ref": item["event_id"],
        "version": item["source_version"],
        "observed_at": item.get("observed_at"),
        "observed_until": item.get("observed_until"),
        "excerpt_redacted": "Trace summary: " + ", ".join(facts),
        "evidence_hash": item["evidence_hash"],
        "component": components[0] if components else None,
        "components": components,
        "signals": [name for name, value in (
            ("trace_failures", summary.get("failed_event_count", 0)),
            ("trace_edges", summary.get("edge_count", 0)),
        ) if int(value or 0) > 0],
    }
