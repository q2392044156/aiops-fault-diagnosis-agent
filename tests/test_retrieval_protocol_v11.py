import json
from pathlib import Path

import pytest

from aiops_diag.data.common import digest
from aiops_diag.retrieval.gate_v11 import CandidateRetriever, calibrate_candidate
import aiops_diag.retrieval.gate_v11 as gate_v11
import aiops_diag.retrieval.blind_v11 as blind_v11
from aiops_diag.retrieval.protocol_v11 import validate_protocol
from aiops_diag.retrieval.blind_v11 import run as run_blind


def _write_jsonl(path, rows):
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8")


def _protocol(tmp_path, reviewed=True):
    sources = [
        {"source_id": "old", "product_version": "3.3.5", "published_at": "2022-01-01", "url": "https://example.org/old"},
        {"source_id": "old2", "product_version": "3.3.6", "published_at": "2023-01-01", "url": "https://example.org/old2"},
        {"source_id": "new", "product_version": "3.3.6", "published_at": "2024-01-01", "url": "https://example.org/new"},
        {"source_id": "new2", "product_version": "3.4.1", "published_at": "2025-01-01", "url": "https://example.org/new2"},
    ]
    cards = tmp_path / "cards"
    cards.mkdir()
    (cards / "doc.json").write_text(json.dumps({
        "doc_id": "doc", "version_scope": ["all-conceptual"],
        "sections": [{"id": "section"}]}), encoding="utf-8")
    manifest = {"schema_version": 2, "sources": sources, "splits": {},
                "knowledge_cards_dir": "cards",
                "legacy_query_files": ["legacy.jsonl", "legacy2.jsonl"]}
    _write_jsonl(tmp_path / "legacy.jsonl", [
        {"query": "已有问题", "family_id": "legacy_family"}])
    _write_jsonl(tmp_path / "legacy2.jsonl", [
        {"query": "已有问题二", "family_id": "legacy_family2"}])
    for split, source_ids in (("development", ("old", "old")),
                              ("calibration", ("old2", "old2")),
                              ("independent_test", ("new", "new2"))):
        count = 60 if split == "independent_test" else 2
        queries = [{"query_id": f"{split}_{index}", "family_id": f"{split}_family_{index}",
                    "split": split, "query": f"{split} 查询 {index}",
                    "has_answer": index < 40 if split == "independent_test" else index == 0,
                    "source_id": source_ids[index % len(source_ids)],
                    "annotator_id": "author", "reviewer_id": "expert",
                    "product_version": next(row["product_version"] for row in sources
                                            if row["source_id"] == source_ids[index % len(source_ids)])}
                   for index in range(count)]
        qrels = [{"query_id": row["query_id"], "evidence_unit_id": "doc:section",
                  "relevance": 2} for row in queries if row["has_answer"]]
        query_path, qrels_path = tmp_path / f"{split}.jsonl", tmp_path / f"{split}_qrels.jsonl"
        _write_jsonl(query_path, queries)
        _write_jsonl(qrels_path, qrels)
        manifest["splits"][split] = {
            "queries": query_path.name, "queries_sha256": digest(query_path),
            "qrels": qrels_path.name, "qrels_sha256": digest(qrels_path),
            "annotation_status": ("independently_reviewed" if reviewed else "self_reviewed")}
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_v11_protocol_requires_sealed_cross_time_version_independent_review(tmp_path):
    path = _protocol(tmp_path)
    result = validate_protocol(path, require_release_ready=True)
    assert result["release_ready"] is True
    assert result["splits"]["independent_test"]["versions"] == ["3.3.6", "3.4.1"]
    with (tmp_path / "independent_test.jsonl").open("a", encoding="utf-8") as stream:
        stream.write("{}\n")
    with pytest.raises(ValueError, match="Sealed"):
        validate_protocol(path)


def test_v11_protocol_refuses_small_reviewed_test(tmp_path):
    path = _protocol(tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    queries_path = tmp_path / "independent_test.jsonl"
    queries = [json.loads(line) for line in queries_path.read_text(
        encoding="utf-8").splitlines()]
    _write_jsonl(queries_path, queries[:-1])
    manifest["splits"]["independent_test"]["queries_sha256"] = digest(queries_path)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert validate_protocol(path)["release_ready"] is False
    with pytest.raises(ValueError, match="Independent review"):
        validate_protocol(path, require_release_ready=True)


def test_v11_protocol_rejects_leakage_and_unreviewed_release(tmp_path):
    path = _protocol(tmp_path, reviewed=False)
    assert validate_protocol(path)["release_ready"] is False
    with pytest.raises(ValueError, match="Independent review"):
        validate_protocol(path, require_release_ready=True)
    data = json.loads(path.read_text(encoding="utf-8"))
    queries_path = tmp_path / "independent_test.jsonl"
    rows = [json.loads(line) for line in queries_path.read_text(encoding="utf-8").splitlines()]
    rows[0]["query"] = "已有问题"
    _write_jsonl(queries_path, rows)
    data["splits"]["independent_test"]["queries_sha256"] = digest(queries_path)
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="leaked"):
        validate_protocol(path)


def test_public_apache_candidate_is_structurally_valid_but_not_a_blind_release_set():
    manifest = Path(__file__).resolve().parents[1] / "evaluation/v1.1/protocol.json"
    result = validate_protocol(manifest)
    assert result["release_ready"] is False
    assert result["splits"]["independent_test"]["versions"] == ["3.4.1", "3.4.2"]
    with pytest.raises(ValueError, match="Independent review"):
        validate_protocol(manifest, require_release_ready=True)


def test_blind_evaluator_does_not_open_current_unreviewed_test_or_write_result(tmp_path):
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "result"
    with pytest.raises(ValueError, match="Independent review"):
        run_blind(root / "configs/agent.yaml", root / "evaluation/v1.1/protocol.json",
                  tmp_path / "calibration.json", root / "configs/service_v11_candidate.yaml",
                  tmp_path / "candidate", output)
    assert not output.exists()


def test_blind_evaluator_writes_immutable_release_bound_comparison(tmp_path, monkeypatch):
    protocol = _protocol(tmp_path)
    output = tmp_path / "blind_result"
    (tmp_path / "calibration.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(blind_v11, "load_agent", lambda _path: {"rag": {"retrieval": "frozen"}})
    monkeypatch.setattr(blind_v11, "verify_candidate", lambda *_args: {
        "status": "READY_FOR_ACCEPTANCE", "release_id": "candidate_123",
        "kb_release_id": "kb_123", "gate_threshold": 0.5})

    class Frozen:
        manifest = {"default_mode": "hybrid", "default_k": 3}

        def __init__(self, _cfg):
            pass

    class Gated:
        def __init__(self, _frozen, _threshold):
            pass

    monkeypatch.setattr(blind_v11, "FrozenRetriever", Frozen)
    monkeypatch.setattr(blind_v11, "CandidateRetriever", Gated)

    def fake_evaluate(engine, queries, _qrels, _mode, _top_k, apply_gate):
        assert apply_gate is True
        rows = [{"query_id": query["query_id"], "family_id": query["family_id"],
                 "has_answer": query["has_answer"],
                 "status": ("insufficient_evidence" if isinstance(engine, Gated)
                            and not query["has_answer"] else "evidence_found"),
                 "recall": 1.0 if query["has_answer"] else None,
                 "mrr": 1.0 if query["has_answer"] else None,
                 "ndcg": 1.0 if query["has_answer"] else None}
                for query in queries]
        return {"metrics": {"query_count": len(rows)}, "queries": rows}

    monkeypatch.setattr(blind_v11, "evaluate", fake_evaluate)
    result = run_blind(tmp_path / "agent.yaml", protocol, tmp_path / "calibration.json",
                       tmp_path / "service.yaml", tmp_path / "release", output)
    assert result["candidate"]["counts"]["no_answer_false_return_count"] == 0
    assert result["baseline"]["counts"]["no_answer_false_return_count"] == 20
    assert result["candidate"]["groups"]["product_version"]["3.4.1"]["queries"] == 30
    assert (output / "manifest.json").is_file()
    with pytest.raises(FileExistsError):
        run_blind(tmp_path / "agent.yaml", protocol, tmp_path / "calibration.json",
                  tmp_path / "service.yaml", tmp_path / "release", output)


def test_candidate_gate_checks_returned_evidence_and_keeps_version_filter():
    class Frozen:
        manifest = {"kb_release_id": "kb_v0.1"}

        def search(self, _query, **kwargs):
            assert kwargs["product_version"] == "3.4.1"
            assert kwargs["apply_gate"] is False
            return {"status": "evidence_found", "mode": "hybrid", "gate_score": 0.9,
                    "items": [{"chunk_id": "ranked_first", "dense_score": 0.4},
                              {"chunk_id": "ranked_second", "dense_score": 0.9}]}

    candidate = CandidateRetriever(Frozen(), 0.5)
    refused = candidate.search("question", product_version="3.4.1")
    assert refused["status"] == "insufficient_evidence"
    assert refused["gate_score"] == 0.4 and refused["items"] == []
    ungated = candidate.search("question", product_version="3.4.1", apply_gate=False)
    assert [row["chunk_id"] for row in ungated["items"]] == ["ranked_first", "ranked_second"]


def test_candidate_calibration_never_opens_test_cases(tmp_path, monkeypatch):
    path = _protocol(tmp_path)
    (tmp_path / "independent_test.jsonl").unlink()
    (tmp_path / "independent_test_qrels.jsonl").unlink()

    class Frozen:
        manifest = {"kb_release_id": "kb_v0.1", "default_mode": "hybrid",
                    "default_k": 3}

    monkeypatch.setattr(gate_v11, "choose_gate_candidate", lambda _gate, queries, _limit: (
        0.5 if len(queries) == 4 else pytest.fail("unexpected query count")))
    monkeypatch.setattr(gate_v11, "evaluate", lambda *_args, **_kwargs: {
        "metrics": {"query_count": 2}})
    result = calibrate_candidate(Frozen(), path)
    assert result["gate_threshold"] == 0.5
    assert result["metrics"]["calibration"]["query_count"] == 2
