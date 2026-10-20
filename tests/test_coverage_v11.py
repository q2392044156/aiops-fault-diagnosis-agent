import json

import pytest

import aiops_diag.retrieval.coverage_v11 as coverage_v11
from aiops_diag.data.common import digest


def test_agent_coverage_comparison_requires_sealed_inputs(tmp_path, monkeypatch):
    case = {"case_id": "event_1", "evidence": [{"kind": "log",
             "component": "DataNode"}], "returned_doc_count": 0}
    cases = tmp_path / "cases.jsonl"
    cases.write_text(json.dumps(case) + "\n", encoding="utf-8")
    manifest = {"status": "REPORT_STABILITY_FIXTURES_ONLY",
                "cases_sha256": digest(cases), "count": 1,
                "kb_release_id": "kb_test", "candidate_release_id": "candidate_test"}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(coverage_v11, "load_agent", lambda _path: {
        "rag": {"retrieval": "frozen"}, "tools": {"runbook_top_k": 3}})

    class Frozen:
        manifest = {"kb_release_id": "kb_test"}

        def __init__(self, _config):
            pass

        def search(self, query, **kwargs):
            assert "DataNode" in query and kwargs["component"] == "DataNode"
            return {"status": "evidence_found"}

    monkeypatch.setattr(coverage_v11, "FrozenRetriever", Frozen)
    result = coverage_v11.compare("agent.yaml", tmp_path)
    assert result["status"] == "COVERAGE_ONLY_NO_RELEVANCE_LABELS"
    assert result["baseline_returned"] == 1 and result["candidate_returned"] == 0
    cases.write_text(cases.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="not sealed"):
        coverage_v11.compare("agent.yaml", tmp_path)
