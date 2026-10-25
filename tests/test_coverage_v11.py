"""模块说明：验证 coverage v11 相关功能、边界和回归行为。"""

import json

import pytest

import aiops_diag.knowledge.coverage_v11 as coverage_v11
from aiops_diag.data.common import digest


# 方法说明：`test_agent_coverage_comparison_requires_sealed_inputs` 完成当前步骤的业务处理；参数为 `tmp_path`、`monkeypatch`。
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

    # 类说明：`Frozen` 封装本模块内聚的数据和行为。
    class Frozen:
        # 变量说明：`manifest` 保存本模块或数据模型使用的稳定值。
        manifest = {"kb_release_id": "kb_test"}

        # 方法说明：`__init__` 完成当前步骤的业务处理；参数为 `_config`。
        def __init__(self, _config):
            pass

        # 方法说明：`search` 完成当前步骤的业务处理；参数为 `query`、`**kwargs`。
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
