import json
import os
import shutil
import statistics
import time
import uuid
from pathlib import Path

from aiops_diag.data.common import digest, key, save
from aiops_diag.retrieval.corpus import read_jsonl
from aiops_diag.retrieval.workflow import validate as validate_retrieval

from .engine import RagEngine, SYSTEM_PROMPT
from .release import verify


def validate(cfg):
    retrieval = validate_retrieval(cfg["retrieval"])
    budget = cfg["budget"]
    if budget["max_total_tokens"] != 2_000_000 or float(budget["max_cost_cny"]) != 20.0:
        raise ValueError("W8 hard budgets must remain 2M tokens and CNY 20")
    if cfg["reranker"]["enabled_by_default"]:
        raise ValueError("The experimental reranker must be disabled by default")
    return {"schema_version": 1, "rag_version": cfg["rag_version"], **retrieval,
            "provider_endpoint": cfg["provider"]["base_url"],
            "reranker_revision": cfg["reranker"]["revision"]}


def _score(rows):
    total = len(rows)
    answerable = [row for row in rows if row["has_answer"]]
    unanswerable = [row for row in rows if not row["has_answer"]]
    return {
        "queries": total,
        "evidence_supported": sum(row["status"] == "EVIDENCE_SUPPORTED" for row in rows),
        "degraded": sum(row["status"] == "DEGRADED_TEMPLATE" for row in rows),
        "insufficient": sum(row["status"] == "INSUFFICIENT_EVIDENCE" for row in rows),
        "answerable_supported_rate": (sum(row["status"] == "EVIDENCE_SUPPORTED"
                                           for row in answerable) / len(answerable)
                                      if answerable else None),
        "unanswerable_refusal_rate": (sum(row["status"] == "INSUFFICIENT_EVIDENCE"
                                            for row in unanswerable) / len(unanswerable)
                                       if unanswerable else None),
        "citation_valid_rate": (sum(row["citation_valid"] for row in rows) / total
                                 if total else None),
        "total_input_tokens": sum(row["input_tokens"] for row in rows),
        "total_output_tokens": sum(row["output_tokens"] for row in rows),
        "estimated_cost_cny": round(sum(row["estimated_cost_cny"] for row in rows), 8),
        "p50_ms": statistics.median(row["elapsed_ms"] for row in rows) if rows else None,
    }


def _run_split(cfg, split):
    evaluation = Path(cfg["retrieval"]["paths"]["evaluation_dir"])
    queries = read_jsonl(evaluation / f"r{split}.jsonl")
    engine = RagEngine(cfg)
    rows = []
    try:
        for item in queries:
            started = time.perf_counter()
            report = engine.generate(item["query"], item.get("component"),
                                     item.get("product_version"), "auto")
            value = report.model_dump()
            cited = {chunk for claim in value["evidence_claims"] for chunk in claim["chunk_ids"]}
            cited.update(chunk for check in value["recommended_checks"]
                         for chunk in check["chunk_ids"])
            rows.append({"query_id": item["query_id"], "family_id": item["family_id"],
                         "has_answer": item["has_answer"], "status": value["status"],
                         "report_id": value["report_id"], "report_hash": value["report_hash"],
                         "citation_valid": cited.issubset(set(value["provenance"]["evidence_chunk_ids"])),
                         "input_tokens": value["provenance"]["input_tokens"],
                         "output_tokens": value["provenance"]["output_tokens"],
                         "estimated_cost_cny": value["provenance"]["estimated_cost_cny"],
                         "elapsed_ms": (time.perf_counter() - started) * 1000,
                         "report": value})
    finally:
        engine.close()
    return rows


def tune(cfg):
    validate(cfg)
    output = Path(cfg["paths"]["work_dir"])
    output.mkdir(parents=True, exist_ok=True)
    rows = _run_split(cfg, "dev")
    value = {"schema_version": 1, "split": "dev", "rag_version": cfg["rag_version"],
             "config_hash": cfg["config_hash"], "prompt_version": cfg["generation"]["prompt_version"],
             "prompt_hash": key(SYSTEM_PROMPT),
             "metrics": _score(rows), "rows": rows}
    save(output / "rdev_results.json", value)
    save(output / "frozen.json", {"schema_version": 1, "config_hash": cfg["config_hash"],
                                   "prompt_version": cfg["generation"]["prompt_version"],
                                   "prompt_hash": key(SYSTEM_PROMPT),
                                   "rdev_results_hash": digest(output / "rdev_results.json")})
    return {name: value[name] for name in ("schema_version", "split", "rag_version", "metrics")}


def publish(cfg):
    work = Path(cfg["paths"]["work_dir"])
    frozen_path = work / "frozen.json"
    if not frozen_path.is_file():
        raise FileNotFoundError("Run Rdev tune before publishing")
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    if frozen["config_hash"] != cfg["config_hash"]:
        raise ValueError("RAG configuration changed after Rdev freeze")
    if frozen.get("prompt_hash") != key(SYSTEM_PROMPT):
        raise ValueError("RAG prompt changed after Rdev freeze")
    kb_manifest = json.loads((Path(cfg["retrieval"]["paths"]["release_dir"])
                              / "retrieval_release.json").read_text(encoding="utf-8"))
    manifest = {"schema_version": 1, "rag_version": cfg["rag_version"],
                "kb_release_id": kb_manifest["kb_release_id"],
                "kb_release_hash": key(kb_manifest), "provider": cfg["provider"]["name"],
                "model": cfg["provider"]["model"],
                "prompt_version": cfg["generation"]["prompt_version"],
                "prompt_hash": key(SYSTEM_PROMPT),
                "config_hash": cfg["config_hash"], "rdev_results_hash": frozen["rdev_results_hash"],
                "reranker_enabled": False,
                "reranker_revision": cfg["reranker"]["revision"]}
    target = Path(cfg["paths"]["release_dir"])
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / f".{target.name}.{uuid.uuid4().hex}.partial"
    try:
        staging.mkdir(parents=True)
        save(staging / "rag_release.json", manifest)
        save(staging / "registry.json", {"schema_version": 1,
                                          "release_hash": key(manifest),
                                          "artifacts": {"rag_release.json":
                                                        digest(staging / "rag_release.json")}})
        previous = target.parent / f".{target.name}.previous"
        if previous.exists():
            shutil.rmtree(previous)
        if target.exists():
            os.replace(target, previous)
        os.replace(staging, target)
        if previous.exists():
            shutil.rmtree(previous)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return verify(cfg)


def finalize(cfg):
    release = verify(cfg)
    output = Path(cfg["paths"]["work_dir"])
    marker = output / "rtest_results.json"
    protocol = Path(cfg["retrieval"]["paths"]["evaluation_dir"]) / "protocol_manifest.json"
    input_hash = key({"release": release, "protocol": digest(protocol)})
    if marker.exists():
        current = json.loads(marker.read_text(encoding="utf-8"))
        if current["input_hash"] != input_hash:
            raise ValueError("Frozen Rtest inputs or RAG release changed")
        return {name: current[name] for name in ("schema_version", "split", "metrics", "input_hash")}
    rows = _run_split(cfg, "test")
    value = {"schema_version": 1, "split": "test", "input_hash": input_hash,
             "metrics": _score(rows), "rows": rows}
    save(marker, value)
    return {name: value[name] for name in ("schema_version", "split", "metrics", "input_hash")}


def fetch_reranker(cfg):
    from huggingface_hub import snapshot_download
    from optimum.exporters.onnx import main_export
    from aiops_diag.retrieval.evaluation import evaluate
    from aiops_diag.retrieval.release import FrozenRetriever
    from .reranker import OnnxReranker, RerankedRetriever

    target = Path(cfg["paths"]["reranker_source_dir"])
    snapshot_download(repo_id=cfg["reranker"]["repo_id"],
                      revision=cfg["reranker"]["revision"], local_dir=target,
                      allow_patterns=["config.json", "model.safetensors", "tokenizer.json",
                                      "tokenizer_config.json", "special_tokens_map.json",
                                      "sentencepiece.bpe.model"], max_workers=1)
    required = (target / "config.json", target / "model.safetensors", target / "tokenizer.json")
    if any(not path.is_file() for path in required):
        raise FileNotFoundError("Official reranker snapshot is incomplete")
    onnx_dir = Path(cfg["paths"]["reranker_onnx_dir"])
    if not (onnx_dir / "model.onnx").is_file():
        main_export(str(target), output=onnx_dir, task="text-classification",
                    monolith=True, library_name="transformers", do_validation=True)
    for name in ("tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"):
        source = target / name
        destination = onnx_dir / name
        if source.is_file() and not destination.is_file():
            shutil.copy2(source, destination)
    reranker = OnnxReranker(onnx_dir)
    import torch
    import numpy as np
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    sample_query = "NameNode连接失败如何排查"
    sample_documents = ["收集NameNode日志和状态", "检查DataNode心跳", "核对安全模式",
                        "删除磁盘文件", "查看HA角色", "确认客户端地址",
                        "执行集群重启", "记录故障时间窗", "检查权限", "查看RPC端口"]
    tokenizer = AutoTokenizer.from_pretrained(target, local_files_only=True)
    model = AutoModelForSequenceClassification.from_pretrained(
        target, local_files_only=True, use_safetensors=True)
    model.eval()
    encoded = tokenizer([sample_query] * len(sample_documents), sample_documents,
                        padding=True, truncation=True, max_length=512, return_tensors="pt")
    with torch.no_grad():
        expected = model(**encoded).logits.detach().cpu().numpy().reshape(-1)
    actual = reranker.score(sample_query, sample_documents)
    maximum = float(np.max(np.abs(expected - actual)))
    ranking_equal = np.argsort(-expected)[:5].tolist() == np.argsort(-actual)[:5].tolist()
    if maximum > 1e-4 or not ranking_equal:
        raise ValueError("ONNX reranker does not match the official safetensors model")
    validation = {"sample_pairs": len(sample_documents), "max_abs_error": maximum,
                  "top5_ranking_equal": ranking_equal}
    base = FrozenRetriever(cfg["retrieval"])
    engine = RerankedRetriever(base, reranker, candidate_k=10,
                               output_k=cfg["reranker"]["top_n"])
    evaluation = Path(cfg["retrieval"]["paths"]["evaluation_dir"])
    queries = read_jsonl(evaluation / "rdev.jsonl")
    qrels = read_jsonl(evaluation / "qrels_dev.jsonl")
    metrics = evaluate(engine, queries, qrels, "hybrid_reranked",
                       cfg["reranker"]["top_n"])["metrics"]
    result = {"schema_version": 1, "repo_id": cfg["reranker"]["repo_id"],
              "revision": cfg["reranker"]["revision"], "default_enabled": False,
              "source_files": {path.name: digest(path) for path in required},
              "onnx_sha256": digest(onnx_dir / "model.onnx"),
              "onnx_validation": validation, "rdev_metrics": metrics}
    output = Path(cfg["paths"]["work_dir"])
    output.mkdir(parents=True, exist_ok=True)
    save(output / "reranker_experiment.json", result)
    return result


def benchmark(cfg):
    engine = RagEngine(cfg)
    try:
        samples = ["NameNode连接失败如何只读排查", "没有匹配证据的火星数据库问题"]
        started = time.perf_counter()
        reports = [engine.generate(query, mode="template") for query in samples]
        return {"schema_version": 1, "requests": len(reports),
                "elapsed_ms": (time.perf_counter() - started) * 1000,
                "statuses": [report.status for report in reports]}
    finally:
        engine.close()
