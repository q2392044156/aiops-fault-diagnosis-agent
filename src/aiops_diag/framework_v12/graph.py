"""Deterministic LangGraph shell around the proven database workflow."""

from collections import Counter
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from aiops_diag.agent.engine import AgentYield
from aiops_diag.agent_v11.engine import AgentEngine as CandidateAgentEngine


class GraphRunState(TypedDict, total=False):
    run: dict
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

    The existing database remains authoritative for node, budget, tool audit,
    approval and recovery state. This first framework phase intentionally uses
    no LangGraph checkpointer, so there is no second source of truth.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.node_execution_counts = Counter()
        self.graph = self._build_graph()

    def _build_graph(self):
        builder = StateGraph(GraphRunState)
        for node_name in GRAPH_NODE_BY_CURRENT.values():
            builder.add_node(node_name, self._advance_database_workflow)
            builder.add_edge(node_name, END)
        builder.add_conditional_edges(START, self._route_current_node,
                                      {name: name for name in GRAPH_NODE_BY_CURRENT.values()})
        return builder.compile()

    @staticmethod
    def _route_current_node(state: GraphRunState) -> str:
        current = state["run"].get("current_node")
        try:
            return GRAPH_NODE_BY_CURRENT[current]
        except KeyError as exc:
            raise ValueError(f"Unsupported persisted Agent node: {current}") from exc

    def _advance_database_workflow(self, state: GraphRunState) -> GraphRunState:
        node_name = self._route_current_node(state)
        if not hasattr(self, "node_execution_counts"):
            self.node_execution_counts = Counter()
        self.node_execution_counts[node_name] += 1
        try:
            report = CandidateAgentEngine.run(self, state["run"])
        except AgentYield as exc:
            return {"yielded_node": str(exc), "completed": False}
        return {"report": report, "completed": True}

    def run(self, run):
        result = self.graph.invoke({"run": run})
        if result.get("completed"):
            return result.get("report")
        raise AgentYield(result["yielded_node"])
