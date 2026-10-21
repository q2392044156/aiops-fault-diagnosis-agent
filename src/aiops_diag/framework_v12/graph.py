"""Deterministic LangGraph shell around the proven database workflow."""

from collections import Counter
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from aiops_diag.agent.engine import AgentYield
from aiops_diag.agent_v11.engine import AgentEngine as CandidateAgentEngine
from aiops_diag.data.common import key


class GraphRunState(TypedDict, total=False):
    diagnosis_id: str
    revision: int
    release_id: str
    current_node: str
    database_state_hash: str
    yielded_node: str
    completed: bool
    report: dict


GRAPH_NODE_BY_CURRENT = {
    "RECEIVED": "validate",
    "VALIDATED": "detect",
    "DETECTED": "collect_evidence",
    "EVIDENCE_COLLECTED": "retrieve",
    "RETRIEVED": "rank_candidates",
    "HYPOTHESES_RANKED": "generate_validate_report",
    "REPORT_VALIDATED": "publish_report",
}


class LangGraphAgentEngine(CandidateAgentEngine):
    """Select one fixed workflow transition through LangGraph per worker lease.

    The business tables remain authoritative for node, budget, tool audit,
    approval and recovery state. v1.2 adds a database-backed LangGraph
    checkpointer containing only compact graph progress; v1.1 keeps it disabled.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.node_execution_counts = Counter()
        self.checkpointer = None
        self._active_run = None
        if self.cfg.get("v12", {}).get("enabled"):
            from aiops_diag.framework_v12.checkpoint import DatabaseCheckpointSaver
            from aiops_diag.framework_v12.tools_v12 import V12AgentTools

            self.checkpointer = DatabaseCheckpointSaver(self.db)
            self.tools = V12AgentTools(
                self.db, self.cfg, self.retriever, self.service_manifest)
        self.graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(GraphRunState)
        for node_name in GRAPH_NODE_BY_CURRENT.values():
            builder.add_node(node_name, self._advance_database_workflow)
            builder.add_edge(node_name, END)
        builder.add_conditional_edges(START, self._route_current_node,
                                      {name: name for name in GRAPH_NODE_BY_CURRENT.values()})
        return builder.compile(checkpointer=getattr(self, "checkpointer", None))

    @staticmethod
    def _route_current_node(state: GraphRunState) -> str:
        current = state.get("current_node")
        try:
            return GRAPH_NODE_BY_CURRENT[current]
        except KeyError as exc:
            raise ValueError(f"Unsupported persisted Agent node: {current}") from exc

    def _advance_database_workflow(self, state: GraphRunState) -> GraphRunState:
        node_name = self._route_current_node(state)
        if not hasattr(self, "node_execution_counts"):
            self.node_execution_counts = Counter()
        self.node_execution_counts[node_name] += 1
        run = getattr(self, "_active_run", None)
        if run is None:
            raise RuntimeError("LangGraph node has no active database run")
        try:
            report = CandidateAgentEngine.run(self, run)
        except AgentYield as exc:
            persisted = (self.db.get_agent_run(run["diagnosis_id"])
                         if hasattr(self, "db") and run.get("diagnosis_id") else run)
            return {"current_node": str(exc), "yielded_node": str(exc),
                    "database_state_hash": key(persisted), "completed": False}
        return {"report": report, "completed": True}

    def run(self, run):
        self._active_run = run
        release = getattr(self, "release", {}) or {}
        pointer = {
            "diagnosis_id": run.get("diagnosis_id", "dia_test"),
            "revision": int(run.get("revision", 1)),
            "release_id": run.get("release_id") or release.get("release_id", "test_release"),
            "current_node": run["current_node"],
            "database_state_hash": key({
                "diagnosis_id": run.get("diagnosis_id", "dia_test"),
                "current_node": run["current_node"],
                "state_json": run.get("state_json"),
                "budget_json": run.get("budget_json"),
            }),
        }
        config = None
        if getattr(self, "checkpointer", None) is not None:
            config = {"configurable": {
                "thread_id": f"{pointer['release_id']}:{pointer['diagnosis_id']}:{pointer['revision']}",
                "checkpoint_ns": "agent-v12",
            }}
        try:
            result = self.graph.invoke(pointer, config)
            if result.get("completed"):
                return result.get("report")
            raise AgentYield(result["yielded_node"])
        finally:
            self._active_run = None

    def _collect_framework_evidence(self, run, state, budget, event_id):
        if not hasattr(self.tools, "read_trace_summary"):
            return [], []
        if not self.db.one("SELECT 1 AS found FROM event_trace_evidence WHERE event_id=?",
                           (event_id,)):
            return [], []
        from aiops_diag.framework_v12.tools_v12 import trace_evidence

        value = self._invoke(
            run, state, budget, "read_trace_summary", {"event_id": event_id},
            lambda: self.tools.read_trace_summary(event_id))
        item = value.get("data", {}).get("item") if value.get("ok") else None
        if not item:
            state["review_reasons"].append("trace_evidence_unavailable")
            return [], []
        evidence = trace_evidence(item)
        components = evidence.get("components") or ([evidence["component"]]
                                                      if evidence.get("component") else [])
        query_rows = [{
            "component": component,
            "level": "ERROR" if "trace_failures" in evidence["signals"] else "INFO",
            "template_id": "trace_summary_v1",
            "redacted_message": " ".join(evidence["signals"]),
        } for component in components]
        return [evidence], query_rows
