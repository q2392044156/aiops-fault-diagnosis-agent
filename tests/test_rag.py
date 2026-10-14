import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from aiops_diag.rag.client import (BudgetExceeded, BudgetLedger, DeepSeekClient,
                                   DeepSeekJsonError)
from aiops_diag.rag.config import load
from aiops_diag.rag.engine import RagEngine
from aiops_diag.rag.release import verify as verify_rag_release
from aiops_diag.data.common import digest, key
from aiops_diag.rag.engine import SYSTEM_PROMPT
from aiops_diag.service.api import create_app
from aiops_diag.service.db import Database


ROOT = Path(__file__).resolve().parents[1]
CHUNK = "chk_" + "a" * 24


class FakeRetriever:
    manifest = {"kb_release_id": "kb_v0.1"}

    def __init__(self, found=True):
        self.found = found

    def search(self, *_args, **_kwargs):
        if not self.found:
            return {"status": "insufficient_evidence", "mode": "hybrid", "items": []}
        return {"status": "evidence_found", "mode": "hybrid", "items": [{
            "chunk_id": CHUNK, "title": "NameNode只读排查", "section_path": "步骤",
            "risk_level": "medium", "text": "先收集日志并确认版本。",
            "source_url": "https://hadoop.apache.org/",
        }]}


class FakeClient:
    configured = True

    def __init__(self, values=None):
        self.values = list(values or [])
        self.calls = 0

    def complete_json(self, _messages):
        self.calls += 1
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        return value, {"input_tokens": 10, "output_tokens": 20,
                       "estimated_cost_cny": 0.00018}

    def close(self):
        pass


def config(tmp_path):
    cfg = load(ROOT / "configs/rag.yaml")
    cfg["paths"]["budget_ledger"] = str(tmp_path / "budget.json")
    return cfg


def valid_body(chunk_id=CHUNK):
    return {"summary": "证据支持先进行只读核验。",
            "evidence_claims": [{"claim": "需要先收集日志。", "chunk_ids": [chunk_id]}],
            "recommended_checks": [{"action": "收集日志", "rationale": "确认时间窗",
                                     "chunk_ids": [chunk_id], "risk": "不得直接变更"}],
            "missing_information": ["版本"], "limitations": ["必须人工复核"]}


def test_no_evidence_never_calls_model(tmp_path):
    client = FakeClient([valid_body()])
    report = RagEngine(config(tmp_path), FakeRetriever(False), client).generate("不存在的问题")
    assert report.status == "INSUFFICIENT_EVIDENCE"
    assert client.calls == 0 and report.provenance.input_tokens == 0


def test_valid_generation_has_traceable_citations(tmp_path):
    client = FakeClient([valid_body()])
    report = RagEngine(config(tmp_path), FakeRetriever(), client).generate("NameNode如何排查")
    assert report.status == "EVIDENCE_SUPPORTED"
    assert report.evidence_claims[0].chunk_ids == [CHUNK]
    assert len(report.report_hash) == 64 and report.requires_review is True


def test_unauthorized_citation_repairs_once_then_degrades(tmp_path):
    other = "chk_" + "b" * 24
    client = FakeClient([valid_body(other), valid_body(other)])
    report = RagEngine(config(tmp_path), FakeRetriever(), client).generate("NameNode如何排查")
    assert client.calls == 2
    assert report.status == "DEGRADED_TEMPLATE"
    assert other not in report.provenance.evidence_chunk_ids


def test_invalid_json_usage_is_counted_and_repaired_once(tmp_path):
    invalid = DeepSeekJsonError("truncated", {"input_tokens": 11, "output_tokens": 12,
                                              "estimated_cost_cny": 0.001})
    client = FakeClient([invalid, valid_body()])
    report = RagEngine(config(tmp_path), FakeRetriever(), client).generate("NameNode如何排查")
    assert client.calls == 2 and report.status == "EVIDENCE_SUPPORTED"
    assert report.provenance.input_tokens == 21
    assert report.provenance.output_tokens == 32


def test_budget_is_hard_and_ledger_contains_no_secret(tmp_path):
    budget = {"max_total_tokens": 100, "max_cost_cny": 1.0,
              "input_cny_per_million": 2.0, "output_cny_per_million": 8.0}
    ledger = BudgetLedger(tmp_path / "ledger.json", budget)
    ledger.record(40, 40)
    with pytest.raises(BudgetExceeded):
        ledger.reserve_check(30)
    text = (tmp_path / "ledger.json").read_text(encoding="utf-8")
    assert "secret" not in text and json.loads(text)["calls"] == 1


def test_deepseek_client_sends_key_only_in_authorization(tmp_path, monkeypatch):
    cfg = config(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret-value")
    captured = {}

    def handler(request):
        captured["authorization"] = request.headers.get("authorization")
        captured["body"] = request.content.decode()
        return httpx.Response(200, json={"choices": [{"message": {"content":
            json.dumps(valid_body(), ensure_ascii=False)}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20}})

    client = DeepSeekClient(cfg, transport=httpx.MockTransport(handler))
    body, _usage = client.complete_json([{"role": "user", "content": "JSON"}])
    client.close()
    assert body["summary"]
    assert captured["authorization"] == "Bearer secret-value"
    assert "secret-value" not in captured["body"]
    assert "secret-value" not in (tmp_path / "budget.json").read_text(encoding="utf-8")


class ApiRag:
    def __init__(self, engine):
        self.engine = engine

    def public(self):
        return self.engine.public()

    def generate(self, *args, **kwargs):
        return self.engine.generate(*args, **kwargs)

    def close(self):
        pass


class ApiRuntime:
    ready = True
    ready_detail = None
    model = None
    retriever = None
    manifest = {"release_id": "v0.2_lr"}

    def __init__(self, tmp_path, engine):
        import threading
        self.rag = ApiRag(engine)
        self.rag_lock = threading.Lock()
        self.db = Database(tmp_path / "service.sqlite3")
        self.db.init()
        self.release = type("Release", (), {"manifest": self.manifest})()

    def stop(self):
        pass


def test_rag_api_persists_and_replays_idempotently(tmp_path):
    engine = RagEngine(config(tmp_path), FakeRetriever(), FakeClient([valid_body()]))
    runtime = ApiRuntime(tmp_path, engine)
    app = create_app({"worker": {}, "registered_batches": {}}, runtime=runtime)
    with TestClient(app) as client:
        first = client.post("/api/v1/rag/reports", json={"query": "NameNode如何排查"},
                            headers={"Idempotency-Key": "same"})
        assert first.status_code == 200
        report_id = first.json()["report_id"]
        second = client.post("/api/v1/rag/reports", json={"query": "NameNode如何排查"},
                             headers={"Idempotency-Key": "same"})
        assert second.json()["report_id"] == report_id
        assert client.get(f"/api/v1/rag/reports/{report_id}").status_code == 200
        conflict = client.post("/api/v1/rag/reports", json={"query": "另一个问题"},
                               headers={"Idempotency-Key": "same"})
        assert conflict.status_code == 409
    assert runtime.db.one("SELECT COUNT(*) AS n FROM rag_reports")["n"] == 1


def test_rag_release_rejects_tampering(tmp_path):
    target = tmp_path / "rag_release"
    target.mkdir()
    kb = tmp_path / "kb_release"
    kb.mkdir()
    (kb / "retrieval_release.json").write_text(
        json.dumps({"kb_release_id": "kb_v0.1"}), encoding="utf-8")
    cfg = load(ROOT / "configs/rag.yaml")
    cfg["paths"]["release_dir"] = str(target)
    cfg["retrieval"]["paths"]["release_dir"] = str(kb)
    manifest = {"schema_version": 1, "rag_version": "rag_v0.1",
                "kb_release_id": "kb_v0.1", "config_hash": cfg["config_hash"],
                "prompt_hash": key(SYSTEM_PROMPT)}
    release_path = target / "rag_release.json"
    release_path.write_text(json.dumps(manifest), encoding="utf-8")
    (target / "registry.json").write_text(json.dumps({"schema_version": 1,
        "release_hash": key(manifest), "artifacts": {
            "rag_release.json": digest(release_path)}}), encoding="utf-8")
    assert verify_rag_release(cfg)["rag_version"] == "rag_v0.1"
    (target / "rag_release.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="Artifact changed"):
        verify_rag_release(cfg)
