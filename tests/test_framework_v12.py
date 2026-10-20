import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from aiops_diag.agent_v11.engine import AgentEngine as CandidateAgentEngine
from aiops_diag.agent.engine import AgentYield
from aiops_diag.framework_v12.graph import (GRAPH_NODE_BY_CURRENT,
                                            LangGraphAgentEngine)
from aiops_diag.framework_v12.release import verify as verify_framework
from aiops_diag.framework_v12.report_chain import CandidateSummaryChain
from aiops_diag.framework_v12.retriever import LangChainRetrieverAdapter
from aiops_diag.service.config import load as load_service
from aiops_diag.service.runtime import ServiceRuntime


ROOT = Path(__file__).resolve().parents[1]


class FakeRetriever:
    manifest = {
        "kb_release_id": "kb_test", "corpus_hash": "corpus_hash",
        "index_hash": "index_hash", "model_hash": "model_hash",
    }

    def __init__(self, status="evidence_found"):
        self.status = status
        self.calls = []

    def search(self, query, **kwargs):
        self.calls.append((query, kwargs))
        items = [] if self.status == "insufficient_evidence" else [{
            "chunk_id": "chk_1", "text": "frozen evidence", "title": "Runbook",
            "section_path": "safe-mode", "source_version": "3.4.1",
            "dense_score": 0.8,
        }]
        return {"status": self.status, "mode": kwargs["mode"], "items": items,
                "gate_score": 0.8, "gate_strategy": "top_result_dense_v11"}

    def verify_integrity(self):
        return True

    def public(self):
        return {"kb_release_id": "kb_test"}

    def chunk(self, chunk_id):
        return {"chunk_id": chunk_id}


def _budget():
    return {"max_tool_calls": 8, "max_llm_calls": 3, "max_tokens": 12000,
            "max_active_ms": 120000, "tool_calls": 0, "llm_calls": 0,
            "tokens": 0, "active_ms": 0, "estimated_cost_cny": 0.0}


def _evidence():
    return [{"evidence_id": "ev_log", "kind": "log", "excerpt_redacted": "log"},
            {"evidence_id": "ev_doc", "kind": "doc", "excerpt_redacted": "doc"}]


def test_framework_dependencies_have_an_independent_exact_lock():
    lock = (ROOT / "requirements-framework-lock.txt").read_text(encoding="utf-8")
    assert "langchain-core==1.6.12" in lock
    assert "langgraph==1.2.16" in lock
    assert not any(line.startswith("-r ") for line in lock.splitlines())


def test_langchain_retriever_preserves_raw_search_and_release_metadata():
    backend = FakeRetriever()
    adapter = LangChainRetrieverAdapter(
        backend=backend, mode="hybrid", top_k=3, component="NameNode",
        product_version="3.4.1")

    raw = adapter.search("safe mode")
    documents = adapter.invoke("safe mode")

    assert raw["status"] == "evidence_found"
    assert raw["items"][0]["chunk_id"] == "chk_1"
    assert documents[0].page_content == "frozen evidence"
    assert documents[0].metadata["chunk_id"] == "chk_1"
    assert documents[0].metadata["retrieval_status"] == "evidence_found"
    assert documents[0].metadata["gate_score"] == 0.8
    assert documents[0].metadata["kb_release_id"] == "kb_test"
    assert documents[0].metadata["corpus_hash"] == "corpus_hash"
    assert all(call[1]["product_version"] == "3.4.1" for call in backend.calls)


def test_langchain_retriever_keeps_fail_closed_empty_result():
    adapter = LangChainRetrieverAdapter(
        backend=FakeRetriever("insufficient_evidence"), mode="hybrid", top_k=3)
    assert adapter.invoke("outside knowledge") == []


def test_langchain_summary_chain_uses_audited_callback_and_strict_parser():
    messages_seen = []

    def invoke_json(messages):
        messages_seen.append(messages)
        return {"summary": "现有证据支持一个待验证候选，仍需人工确认。"}

    result = CandidateSummaryChain().invoke({"allowed_evidence_ids": ["ev_doc"]},
                                            invoke_json)
    assert result == {"summary": "现有证据支持一个待验证候选，仍需人工确认。"}
    assert [message["role"] for message in messages_seen[0]] == ["system", "user"]
    assert json.loads(messages_seen[0][1]["content"])["allowed_evidence_ids"] == ["ev_doc"]


def test_candidate_langchain_backend_repairs_once_through_existing_llm_budget_path():
    engine = object.__new__(CandidateAgentEngine)
    engine.client = SimpleNamespace(configured=True)
    engine.summary_chain = CandidateSummaryChain()
    replies = iter([
        {"summary": "重启 NameNode"},
        {"summary": "现有证据支持一个待验证候选，仍需人工确认。"},
    ])
    messages_seen = []

    def llm(_budget_value, messages):
        messages_seen.append(messages)
        return next(replies)

    engine._llm = llm
    state = {"errors": []}
    body, status = engine._generate(
        {"mode": "auto"}, state, _budget(), {}, [], _evidence())

    assert status == "EVIDENCE_SUPPORTED"
    assert body.summary.endswith("人工确认。")
    assert len(messages_seen) == 2
    assert [message["role"] for message in messages_seen[1]] == [
        "system", "user", "assistant", "user"]
    assert state["errors"][0]["reason"] == "operational_text"


def test_langgraph_routes_each_persisted_node_to_a_fixed_named_node(monkeypatch):
    engine = object.__new__(LangGraphAgentEngine)
    engine.graph = engine._build_graph()
    seen = []

    def legacy_step(_engine, run):
        seen.append(run["current_node"])
        raise AgentYield("DETECTED")

    monkeypatch.setattr(CandidateAgentEngine, "run", legacy_step)
    with pytest.raises(AgentYield, match="DETECTED"):
        engine.run({"current_node": "VALIDATED"})

    assert seen == ["VALIDATED"]
    assert set(engine.graph.get_graph().nodes) >= {
        "__start__", *GRAPH_NODE_BY_CURRENT.values(), "__end__"}


def test_langgraph_has_no_framework_checkpointer_in_database_authority_phase():
    engine = object.__new__(LangGraphAgentEngine)
    engine.graph = engine._build_graph()
    assert engine.graph.checkpointer is None


def test_framework_candidate_release_and_runtime_are_bound_to_new_backends(tmp_path):
    cfg = load_service(ROOT / "configs/service_framework_rc2.yaml")
    release = verify_framework(
        cfg["agent"], cfg["v11_candidate"], cfg["framework_candidate"],
        cfg["config_path"], cfg["framework_candidate"]["release_dir"])
    cfg["paths"]["runtime_dir"] = str(tmp_path / "runtime")
    cfg["paths"]["database"] = str(tmp_path / "runtime/service.sqlite3")
    runtime = ServiceRuntime(cfg, role="worker")
    try:
        assert runtime.ready_error is None
        assert isinstance(runtime.agent, LangGraphAgentEngine)
        assert isinstance(runtime.retriever, LangChainRetrieverAdapter)
        assert runtime.agent.report_backend == "langchain"
        assert runtime.agent_release["release_id"] == release["release_id"]
        assert release["status"] == "READY_FOR_FLOW_VALIDATION"
        assert release["production_ready"] is False
        assert release["prior_blind_observation"][
            "reusable_for_tuning_or_acceptance"] is False
    finally:
        runtime.stop()


def test_langgraph_candidate_runs_all_database_nodes_to_review(tmp_path):
    cfg = load_service(ROOT / "configs/service_framework_rc2.yaml")
    cfg["paths"]["runtime_dir"] = str(tmp_path / "runtime")
    cfg["paths"]["database"] = str(tmp_path / "runtime/service.sqlite3")
    runtime = ServiceRuntime(cfg, role="worker")
    try:
        stamp = datetime.now(timezone.utc).isoformat()
        with runtime.db.transaction() as raw:
            raw.execute(
                "INSERT INTO batches(batch_id,source_kind,source_ref,input_hash,release_id,"
                "processing_hash,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                ("bat_graph", "upload", "x", "h", "v0.2_lr", "p", "SUCCEEDED",
                 stamp, stamp))
            raw.execute(
                "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("evt_graph", "bat_graph", None, "2026-01-01T00:00:00",
                 "2026-01-01T00:01:00", stamp, 5.0, 4.0, 1, "OPEN"))
        diagnosis_id = "dia_" + "f" * 24
        runtime.db.create_agent_run(
            diagnosis_id, "evt_graph", "template", runtime.agent_release["release_id"],
            "framework-flow", _budget())
        visited = []
        for _ in range(10):
            run = runtime.db.claim_agent("framework-test", 30)
            if run is None:
                break
            visited.append(run["current_node"])
            runtime._run_agent(run, 30, 5)
        final = runtime.db.get_agent_run(diagnosis_id)
        assert visited == ["RECEIVED", "VALIDATED", "DETECTED", "EVIDENCE_COLLECTED",
                           "RETRIEVED", "HYPOTHESES_RANKED"]
        assert final["status"] == "WAITING_REVIEW"
        report = json.loads(runtime.db.one(
            "SELECT report_json FROM incident_reports WHERE diagnosis_id=?",
            (diagnosis_id,))["report_json"])
        assert report["diagnosis_status"] == "INSUFFICIENT_EVIDENCE"
        assert report["provenance"]["agent_version"] == (
            "agent_v0.4.1_langgraph")
        assert all(item["execution_allowed"] is False for item in report["checks"])
        assert final["budget"]["llm_calls"] == 0
    finally:
        runtime.stop()
