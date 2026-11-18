"""围绕既有数据库工作流的确定性 LangGraph 外壳：每次调用只推进一个持久化节点。"""

from collections import Counter
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from aiops_diag.common import key
from online.diagnosis.agent import AgentYield
from online.diagnosis.candidate import CandidateAgent


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


class LangGraphAgent(CandidateAgent):
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
            from online.diagnosis.framework.checkpoint import DatabaseCheckpointSaver
            from online.diagnosis.framework.tools import CheckpointTools

            self.checkpointer = DatabaseCheckpointSaver(self.db)
            self.tools = CheckpointTools(
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
            report = CandidateAgent.run(self, run)
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


