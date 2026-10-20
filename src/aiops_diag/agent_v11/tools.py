"""Candidate-only tool diagnostics without changing the frozen v1.0 tools."""

from aiops_diag.agent.tools import AgentTools


class CandidateAgentTools(AgentTools):
    def detect_anomaly(self, event_id):
        value = super().detect_anomaly(event_id)
        if value.get("ok"):
            value["data"]["event"].update(self.db.get_event_metadata(event_id))
        return value

    def retrieve_runbook(self, query, component=None, product_version=None, top_k=3):
        value = super().retrieve_runbook(query, component, product_version, top_k)
        if not value.get("ok"):
            return value
        raw = self.retriever.search(
            query, mode="frozen", top_k=int(top_k), component=component,
            product_version=product_version, apply_gate=False)
        candidates = [{name: item.get(name) for name in (
            "chunk_id", "doc_id", "section_path", "source_version",
            "rrf_score", "dense_score", "bm25_score")}
            for item in raw.get("items", [])]
        top_score = raw.get("gate_score")
        if top_score is None and raw.get("items"):
            top_score = raw["items"][0].get("dense_score")
        second_score = (raw["items"][1].get("dense_score")
                        if len(raw.get("items", [])) > 1 else None)
        if value["data"].get("status") == "evidence_found":
            reason = "passed"
        elif top_score is None:
            reason = "no_candidate"
        else:
            reason = "below_threshold"
        value["data"]["gate_diagnostics"] = {
            "reason": reason,
            "pre_gate_candidates": candidates,
            "top1_top2_dense_gap": (
                top_score - second_score
                if top_score is not None and second_score is not None else None),
        }
        return value

