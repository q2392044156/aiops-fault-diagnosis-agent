"""模块说明：验证 retrieval 相关功能、边界和回归行为。"""

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import httpx
from fastapi.testclient import TestClient

from aiops_diag.data.common import digest
from aiops_diag.knowledge.config import load
from aiops_diag.knowledge.corpus import chunk_structured, load_sources, validate_corpus
from aiops_diag.knowledge.engine import BM25, Retriever, reciprocal_rank_fusion, tokenize
from aiops_diag.knowledge.gate_v11 import choose_gate_candidate
from aiops_diag.knowledge.release import FrozenRetriever, verify
from aiops_diag.knowledge.workflow import validate
import aiops_diag.knowledge.workflow as retrieval_workflow
from aiops_diag.platform.api import create_app
from aiops_diag.platform.ui_client import ApiClient


# 变量说明：`ROOT` 保存本模块或数据模型使用的稳定值。
ROOT = Path(__file__).resolve().parents[1]


# 方法说明：`retrieval_cfg` 完成当前步骤的业务处理；参数为 无显式业务参数。
def retrieval_cfg():
    return load(ROOT / "resources/configs/retrieval.yaml")


# 方法说明：`test_corpus_and_query_protocol_are_complete_and_isolated` 完成当前步骤的业务处理；参数为 无显式业务参数。
def test_corpus_and_query_protocol_are_complete_and_isolated():
    cfg = retrieval_cfg()
    result = validate(cfg)
    assert result["card_count"] >= 30
    assert result["rdev_queries"] == 60
    assert result["rtest_queries"] == 60
    assert result["family_overlap"] == 0
    cards, sources = validate_corpus(cfg)
    chunks_a = chunk_structured(cards, {row["source_id"]: row for row in sources}, "kb_v0.1")
    chunks_b = chunk_structured(cards, {row["source_id"]: row for row in sources}, "kb_v0.1")
    assert len(chunks_a) == len(cards) * 4
    assert [row["chunk_id"] for row in chunks_a] == [row["chunk_id"] for row in chunks_b]


# 方法说明：`test_development_validation_does_not_parse_sealed_rtest` 完成当前步骤的业务处理；参数为 `monkeypatch`。
def test_development_validation_does_not_parse_sealed_rtest(monkeypatch):
    original = retrieval_workflow.read_jsonl
    parsed = []

    # 方法说明：`traced` 完成当前步骤的业务处理；参数为 `path`。
    def traced(path):
        parsed.append(Path(path).name)
        if Path(path).name in {"rtest.jsonl", "qrels_test.jsonl"}:
            raise AssertionError("development path parsed sealed Rtest content")
        return original(path)

    monkeypatch.setattr(retrieval_workflow, "read_jsonl", traced)
    validate(retrieval_cfg())
    assert parsed == ["rdev.jsonl", "qrels_dev.jsonl"]


# 方法说明：`test_bm25_and_tokenizer_preserve_operational_terms` 完成当前步骤的业务处理；参数为 无显式业务参数。
def test_bm25_and_tokenizer_preserve_operational_terms():
    documents = [tokenize("NameNode checksum ERROR_CODE_42"), tokenize("DataNode 心跳 正常")]
    model = BM25(documents, 1.5, 0.75)
    scores = model.score("checksum ERROR_CODE_42")
    assert scores[0] > scores[1]
    assert "error_code_42" in documents[0]


# 方法说明：`test_rrf_uses_ranks_not_raw_scores` 完成当前步骤的业务处理；参数为 无显式业务参数。
def test_rrf_uses_ranks_not_raw_scores():
    scores = reciprocal_rank_fusion([2, 1, 0], [0, 2, 1], 60)
    assert scores[2] > scores[1]
    assert scores[2] > 0


# 类说明：`_Encoder` 封装本模块内聚的数据和行为。
class _Encoder:
    # 方法说明：`encode` 完成当前步骤的业务处理；参数为 `texts`、`query`。
    def encode(self, texts, query=False):
        return np.asarray([[1.0, 0.0] for _ in texts], dtype=np.float32)


# 方法说明：`test_retriever_gate_and_version_filter` 完成当前步骤的业务处理；参数为 无显式业务参数。
def test_retriever_gate_and_version_filter():
    chunks = [{"chunk_id": "a", "text": "NameNode safe mode", "component": ["NameNode"],
               "version_scope": ["3.3.5"]},
              {"chunk_id": "b", "text": "DataNode heartbeat", "component": ["DataNode"],
               "version_scope": ["all-conceptual"]}]
    engine = Retriever(chunks, BM25([tokenize(row["text"]) for row in chunks]),
                       np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32), _Encoder(),
                       gate_threshold=0.9)
    assert engine.search("safe mode", component="NameNode", product_version="3.3.5")["items"][0]["chunk_id"] == "a"
    assert engine.search("safe mode", component="NameNode", product_version="2.0")["status"] == "insufficient_evidence"


# 方法说明：`test_gate_calibration_uses_query_product_version` 完成当前步骤的业务处理；参数为 无显式业务参数。
def test_gate_calibration_uses_query_product_version():
    seen = []

    # 类说明：`ScoredEngine` 封装本模块内聚的数据和行为。
    class ScoredEngine:
        # 方法说明：`search` 完成当前步骤的业务处理；参数为 `_query`、`**kwargs`。
        def search(self, _query, **kwargs):
            seen.append(kwargs["product_version"])
            return {"gate_score": 0.8 if kwargs["product_version"] == "3.3.5" else 0.2}

    queries = [{"query": "supported", "has_answer": True, "product_version": "3.3.5"},
               {"query": "other", "has_answer": False, "product_version": "3.4.1"}]
    assert choose_gate_candidate(ScoredEngine(), queries, 0.0) == 0.8
    assert seen == ["3.3.5", "3.4.1"]


# 方法说明：`test_release_verification_rejects_tampering` 完成当前步骤的业务处理；参数为 `tmp_path`。
def test_release_verification_rejects_tampering(tmp_path):
    release = {"schema_version": 1, "kb_release_id": "kb_v0.1"}
    path = tmp_path / "retrieval_release.json"
    path.write_text(json.dumps(release), encoding="utf-8")
    registry = {"schema_version": 1, "artifacts": {"retrieval_release.json": digest(path)}}
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    cfg = {"kb_version": "kb_v0.1", "paths": {"release_dir": str(tmp_path)}}
    assert verify(cfg)["kb_release_id"] == "kb_v0.1"
    pinned = {**cfg, "release_integrity": {"registry_sha256": digest(registry_path),
              "manifest_sha256": digest(path)}}
    registry_path.write_text(json.dumps(registry) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Pinned knowledge release file changed"):
        verify(pinned)
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Artifact changed"):
        verify(cfg)


# 方法说明：`test_loaded_retriever_detects_runtime_tampering` 完成当前步骤的业务处理；参数为 `tmp_path`。
def test_loaded_retriever_detects_runtime_tampering(tmp_path):
    release = {"schema_version": 1, "kb_release_id": "kb_v0.1"}
    release_path = tmp_path / "retrieval_release.json"
    artifact = tmp_path / "index.bin"
    release_path.write_text(json.dumps(release), encoding="utf-8")
    artifact.write_bytes(b"original")
    registry = {"schema_version": 1, "artifacts": {
        "retrieval_release.json": digest(release_path), "index.bin": digest(artifact)}}
    (tmp_path / "registry.json").write_text(json.dumps(registry), encoding="utf-8")
    retriever = FrozenRetriever.__new__(FrozenRetriever)
    retriever.cfg = {"kb_version": "kb_v0.1", "paths": {"release_dir": str(tmp_path)}}
    retriever.directory = tmp_path
    retriever.manifest = release
    retriever._stats = retriever._artifact_stats()
    assert retriever.verify_integrity()
    artifact.write_bytes(b"changed")
    with pytest.raises(ValueError, match="Artifact changed"):
        retriever.verify_integrity()


# 类说明：`_Release` 封装本模块内聚的数据和行为。
class _Release:
    # 变量说明：`manifest` 保存本模块或数据模型使用的稳定值。
    manifest = {"release_id": "v0.2_lr"}
    # 方法说明：`public` 完成当前步骤的业务处理；参数为 无显式业务参数。
    def public(self):
        return {"schema_version": 2, "deployment_release": "v0.3",
                "release_id": "v0.2_lr", "model_id": "logistic_regression",
                "model_family": "tfidf_lr", "threshold": 1.0,
                "anomaly_score_semantics": "larger_is_more_anomalous_uncalibrated",
                "protocol_hash": "p", "template_manifest_hash": "t"}


# 类说明：`_Knowledge` 封装本模块内聚的数据和行为。
class _Knowledge:
    # 变量说明：`manifest` 保存本模块或数据模型使用的稳定值。
    manifest = {"kb_release_id": "kb_v0.1"}
    # 方法说明：`public` 完成当前步骤的业务处理；参数为 无显式业务参数。
    def public(self):
        return {"schema_version": 1, "kb_release_id": "kb_v0.1", "corpus_hash": "c",
                "index_hash": "i", "model_revision": "r", "model_hash": "m",
                "default_mode": "hybrid", "default_k": 3, "gate_threshold": 0.5,
                "chunk_variant": "fixed", "chunk_count": 1}
    # 方法说明：`search` 完成当前步骤的业务处理；参数为 `*args`、`**kwargs`。
    def search(self, *args, **kwargs):
        row = {"rank": 1, "chunk_id": "chk_" + "a" * 24, "doc_id": "doc", "title": "标题",
               "section_path": "步骤", "text": "证据", "component": ["NameNode"],
               "product": "HDFS", "version_scope": ["3.3.5"], "risk_level": "medium",
               "source_id": "apache", "source_url": "https://hadoop.apache.org/",
               "source_version": "3.3.5", "maintained_at": "2026-10-13",
               "bm25_score": 1.0, "dense_score": 0.8, "rrf_score": 0.03}
        return {"status": "evidence_found", "mode": "hybrid", "items": [row]}
    # 方法说明：`chunk` 完成当前步骤的业务处理；参数为 `chunk_id`。
    def chunk(self, chunk_id):
        item = self.search()["items"][0]
        return item if item["chunk_id"] == chunk_id else None


# 类说明：`_Runtime` 封装本模块内聚的数据和行为。
class _Runtime:
    # 变量说明：`ready` 保存本模块或数据模型使用的稳定值。
                  # 变量说明：`ready_detail` 保存本模块或数据模型使用的稳定值。
                                       # 变量说明：`model` 保存本模块或数据模型使用的稳定值。
    ready = True; ready_detail = None; model = None
    # 变量说明：`release` 保存本模块或数据模型使用的稳定值。
                          # 变量说明：`retriever` 保存本模块或数据模型使用的稳定值。
                                                    # 变量说明：`manifest` 保存本模块或数据模型使用的稳定值。
    release = _Release(); retriever = _Knowledge(); manifest = release.manifest
    # 方法说明：`stop` 完成当前步骤的业务处理；参数为 无显式业务参数。
    def stop(self): pass


# 方法说明：`test_retrieval_api_returns_only_registered_evidence` 完成当前步骤的业务处理；参数为 无显式业务参数。
def test_retrieval_api_returns_only_registered_evidence():
    app = create_app({"worker": {}, "registered_batches": {}}, runtime=_Runtime())
    with TestClient(app) as client:
        response = client.post("/api/v1/retrieval/search", json={"query": "safe mode"})
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "evidence_found"
        chunk_id = body["items"][0]["chunk_id"]
        assert client.get(f"/api/v1/knowledge/chunks/{chunk_id}").status_code == 200
        assert client.get("/api/v1/knowledge/chunks/not-a-chunk").status_code == 422
        unknown = "chk_" + "b" * 24
        assert client.get(f"/api/v1/knowledge/chunks/{unknown}").status_code == 404
        assert client.post("/api/v1/retrieval/search", json={"query": "x", "top_k": 11}).status_code == 422


# 方法说明：`test_ui_client_handles_empty_results_and_api_unavailable` 完成当前步骤的业务处理；参数为 无显式业务参数。
def test_ui_client_handles_empty_results_and_api_unavailable():
    # 方法说明：`empty_handler` 完成当前步骤的业务处理；参数为 `request`。
    def empty_handler(request):
        assert request.url.path == "/api/v1/retrieval/search"
        return httpx.Response(200, json={"schema_version": 1, "kb_release_id": "kb_v0.1",
            "mode": "hybrid", "status": "insufficient_evidence", "elapsed_ms": 1.0,
            "items": []})

    client = ApiClient("http://api", transport=httpx.MockTransport(empty_handler))
    assert client.retrieve("没有对应知识的查询")["status"] == "insufficient_evidence"
    client.close()

    # 方法说明：`unavailable` 完成当前步骤的业务处理；参数为 `_request`。
    def unavailable(_request):
        raise httpx.ConnectError("API unavailable")

    client = ApiClient("http://api", transport=httpx.MockTransport(unavailable))
    with pytest.raises(httpx.ConnectError, match="unavailable"):
        client.knowledge_release()
    client.close()
