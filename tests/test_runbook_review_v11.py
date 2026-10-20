import json

import pytest

import aiops_diag.retrieval.runbook_review_v11 as review
from aiops_diag.data.common import digest


def _write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n"
                            for row in rows), encoding="utf-8")


def test_blind_packet_and_sealed_relevance_scoring(tmp_path, monkeypatch):
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    case = {"case_id": "event_1", "event": {"start_time": "t1", "end_time": "t2"},
            "evidence": [{"kind": "log", "component": "DataNode", "level": "WARN",
                          "observed_at": "t1", "excerpt_redacted": "WARN block unavailable"}],
            "log_count": 1, "returned_doc_count": 0}
    _write_jsonl(fixtures / "cases.jsonl", [case])
    (fixtures / "manifest.json").write_text(json.dumps({
        "status": "REPORT_STABILITY_FIXTURES_ONLY", "count": 1,
        "kb_release_id": "kb_test", "candidate_release_id": "agent_test",
        "cases_sha256": digest(fixtures / "cases.jsonl")}), encoding="utf-8")
    monkeypatch.setattr(review, "load_agent", lambda _: {
        "rag": {"retrieval": "frozen"}, "tools": {"runbook_top_k": 3}})

    class Frozen:
        manifest = {"kb_release_id": "kb_test"}

        def __init__(self, _):
            pass

        def search(self, query, **kwargs):
            assert "DataNode" in query
            return {"status": "evidence_found", "items": [{"chunk_id": "doc_1"}]}

        def chunk(self, chunk_id):
            return {"chunk_id": chunk_id, "title": "DataNode checks",
                    "section_path": "checks", "source_url": "https://example.org",
                    "source_version": "3.3.5", "text": "Read-only check"}

    monkeypatch.setattr(review, "FrozenRetriever", Frozen)
    out = tmp_path / "review"
    manifest = review.build("agent.yaml", fixtures, out)
    assert manifest["case_count"] == 1
    packet = review._rows(out / "packet.jsonl")
    assert "baseline_doc_ids" not in packet[0]
    assert "candidate_doc_ids" not in packet[0]
    assert "return_map" not in packet[0]
    assert packet[0]["review_relevance"] == {"doc_1": None}
    packet[0]["review_relevance"] = {"doc_1": 2}
    packet[0]["reviewer_id"] = "external_reviewer"
    packet[0]["review_notes"] = "Checks directly address the warning."
    submission = tmp_path / "labels.jsonl"
    _write_jsonl(submission, packet)
    scored = review.evaluate(out, submission)
    assert scored["baseline_only_relevant"] == 1
    assert scored["candidate_any_relevant"] == 0
    packet[0]["review_relevance"] = {"doc_1": True}
    _write_jsonl(submission, packet)
    with pytest.raises(ValueError, match="Relevance labels"):
        review.evaluate(out, submission)
    (out / "return_map.private.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        review.evaluate(out, submission)
