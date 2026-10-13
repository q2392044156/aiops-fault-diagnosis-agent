import json
import os
import shutil
import statistics
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import psutil
from tokenizers import Tokenizer

from aiops_diag.data.common import digest, key, save, verified_manifest

from .corpus import (chunk_fixed, chunk_structured, load_cards, load_sources, read_jsonl,
                     validate_corpus, write_jsonl)
from .dense import OnnxEncoder
from .engine import BM25, Retriever, tokenize
from .evaluation import choose_gate, evaluate, validate_queries
from .release import FrozenRetriever, verify


def _model_files(cfg):
    directory = Path(cfg["paths"]["model_onnx_dir"])
    return {name: directory / name for name in (
        "model.onnx", "tokenizer.json", "config.json", "tokenizer_config.json",
        "special_tokens_map.json", "vocab.txt")}


def validate(cfg):
    cards, _sources = validate_corpus(cfg)
    evaluation = Path(cfg["paths"]["evaluation_dir"])
    units = {f"{card['doc_id']}:{section['id']}" for card in cards for section in card["sections"]}
    protocol = json.loads((evaluation / "protocol_manifest.json").read_text(encoding="utf-8"))
    paths = {
        "rdev_queries": evaluation / "rdev.jsonl",
        "rdev_qrels": evaluation / "qrels_dev.jsonl",
        "rtest_queries": evaluation / "rtest.jsonl",
        "rtest_qrels": evaluation / "qrels_test.jsonl",
    }
    expected = {
        "rdev_queries": protocol["rdev"]["queries_sha256"],
        "rdev_qrels": protocol["rdev"]["qrels_sha256"],
        "rtest_queries": protocol["rtest"]["queries_sha256"],
        "rtest_qrels": protocol["rtest"]["qrels_sha256"],
    }
    for name, path in paths.items():
        if digest(path) != expected[name]:
            raise ValueError(f"Sealed evaluation artifact changed: {name}")
    queries = read_jsonl(paths["rdev_queries"])
    qrels = read_jsonl(paths["rdev_qrels"])
    validate_queries(queries, qrels, "dev")
    if any(row["evidence_unit_id"] not in units for row in qrels):
        raise ValueError("Rdev qrel refers to an unknown evidence unit")
    dev_families = {item["family_id"] for item in queries}
    test_families = set(protocol["rtest"]["family_ids"])
    if len(test_families) != protocol["rtest"]["query_count"]:
        raise ValueError("Sealed Rtest family metadata contains duplicates")
    if dev_families & test_families:
        raise ValueError("Rdev and Rtest question families overlap")
    return {"card_count": len(cards), "rdev_queries": len(queries),
            "rtest_queries": protocol["rtest"]["query_count"], "family_overlap": 0}


def fetch_model(cfg):
    from huggingface_hub import snapshot_download
    from optimum.exporters.onnx import main_export

    source = Path(cfg["paths"]["model_source_dir"])
    target = Path(cfg["paths"]["model_onnx_dir"])
    patterns = ["config.json", "model.safetensors", "tokenizer.json",
                "tokenizer_config.json", "special_tokens_map.json", "vocab.txt",
                "modules.json", "1_Pooling/config.json", "config_sentence_transformers.json",
                "sentence_bert_config.json"]
    snapshot_download(repo_id=cfg["model"]["repo_id"], revision=cfg["model"]["revision"],
                      local_dir=source, allow_patterns=patterns, max_workers=1)
    if not (target / "model.onnx").is_file():
        main_export(str(source), output=target, task="feature-extraction", monolith=True,
                    library_name="transformers", do_validation=True)
    files = _model_files(cfg)
    if any(not path.is_file() for path in files.values()):
        raise FileNotFoundError("ONNX export is incomplete")
    validation = validate_model_export(cfg)
    manifest = {"schema_version": 1, "repo_id": cfg["model"]["repo_id"],
                "revision": cfg["model"]["revision"],
                "source_safetensors_hash": digest(source / "model.safetensors"),
                "validation": validation,
                "artifacts": {name: digest(path) for name, path in files.items()}}
    save(target / "model_manifest.json", manifest)
    return manifest


def validate_model_export(cfg):
    import torch
    from transformers import AutoModel, AutoTokenizer

    texts = ["NameNode处于安全模式", "DataNode心跳缺失", "block副本不足",
             "HDFS写入pipeline超时", "磁盘空间不足", "权限拒绝", "配额超限",
             "JournalNode多数派异常", "Standby同步滞后", "校验和不一致",
             "文件租约恢复", "小文件导致元数据压力", "机架感知配置", "Balancer评估",
             "证据时间窗", "日志时区未知", "重启风险", "磁盘清理边界",
             "网络故障升级", "证据不足停止"]
    source = cfg["paths"]["model_source_dir"]
    tokenizer = AutoTokenizer.from_pretrained(source, local_files_only=True)
    model = AutoModel.from_pretrained(source, local_files_only=True, use_safetensors=True)
    model.eval()
    encoded = tokenizer(texts, padding=True, truncation=True,
                        max_length=cfg["model"]["max_length"], return_tensors="pt")
    with torch.no_grad():
        vector = model(**encoded).last_hidden_state[:, 0, :]
        expected = torch.nn.functional.normalize(vector, p=2, dim=1).cpu().numpy()
    actual = OnnxEncoder(cfg["paths"]["model_onnx_dir"], cfg["model"]["query_prefix"],
                         cfg["model"]["max_length"], cfg["model"]["batch_size"]).encode(texts)
    maximum = float(np.max(np.abs(expected - actual)))
    expected_order = np.argsort(-(expected[1:] @ expected[0]))[:5].tolist()
    actual_order = np.argsort(-(actual[1:] @ actual[0]))[:5].tolist()
    if maximum > 1e-4 or expected_order != actual_order:
        raise ValueError("ONNX export does not match the source BGE model")
    return {"sample_count": len(texts), "max_abs_error": maximum,
            "top5_ranking_equal": True}


def _write_build(cfg, variant, chunks, encoder):
    directory = Path(cfg["paths"]["work_dir"]) / variant
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True)
    chunks = sorted(chunks, key=lambda row: row["chunk_id"])
    write_jsonl(directory / "chunks.jsonl", chunks)
    bm25 = BM25([tokenize(row["text"]) for row in chunks], cfg["bm25"]["k1"],
                cfg["bm25"]["b"])
    save(directory / "bm25.json", bm25.serializable())
    started = time.perf_counter()
    vectors = encoder.encode([row["text"] for row in chunks], query=False)
    np.save(directory / "dense.npy", vectors, allow_pickle=False)
    build_info = {"schema_version": 1, "variant": variant, "chunk_count": len(chunks),
                  "dimension": int(vectors.shape[1]),
                  "embedding_seconds": time.perf_counter() - started}
    save(directory / "build.json", build_info)
    artifacts = {name: digest(directory / name) for name in
                 ("chunks.jsonl", "bm25.json", "dense.npy", "build.json")}
    save(directory / "manifest.json", {"schema_version": 1, "artifacts": artifacts})
    return build_info


def build(cfg):
    validate(cfg)
    cards, sources = validate_corpus(cfg)
    sources = {row["source_id"]: row for row in sources}
    files = _model_files(cfg)
    if any(not path.is_file() for path in files.values()):
        raise FileNotFoundError("Run fetch-model before building retrieval indexes")
    tokenizer = Tokenizer.from_file(str(files["tokenizer.json"]))
    encoder = OnnxEncoder(cfg["paths"]["model_onnx_dir"], cfg["model"]["query_prefix"],
                          cfg["model"]["max_length"], cfg["model"]["batch_size"])
    structured = chunk_structured(cards, sources, cfg["kb_version"])
    fixed = chunk_fixed(cards, sources, cfg["kb_version"], tokenizer,
                        cfg["chunking"]["fixed_tokens"], cfg["chunking"]["fixed_overlap"])
    return {"structured": _write_build(cfg, "structured", structured, encoder),
            "fixed": _write_build(cfg, "fixed", fixed, encoder)}


def _load_engine(cfg, variant, mode="hybrid", top_k=5, threshold=None):
    directory = Path(cfg["paths"]["work_dir"]) / variant
    verified_manifest(directory, "manifest.json")
    chunks = read_jsonl(directory / "chunks.jsonl")
    data = json.loads((directory / "bm25.json").read_text(encoding="utf-8"))
    bm25 = BM25(data["tokens"], data["k1"], data["b"])
    vectors = np.load(directory / "dense.npy", allow_pickle=False)
    encoder = OnnxEncoder(cfg["paths"]["model_onnx_dir"], cfg["model"]["query_prefix"],
                          cfg["model"]["max_length"], cfg["model"]["batch_size"])
    return Retriever(chunks, bm25, vectors, encoder, cfg["retrieval"]["candidate_k"],
                     cfg["retrieval"]["rrf_constant"], mode, top_k, threshold)


def _inputs_hash(cfg, split):
    paths = [Path(cfg["paths"]["cards_dir"]) / name
             for name in sorted(path.name for path in Path(cfg["paths"]["cards_dir"]).glob("*.json"))]
    evaluation = Path(cfg["paths"]["evaluation_dir"])
    paths += [Path(cfg["paths"]["sources"]), evaluation / f"r{split}.jsonl",
              evaluation / f"qrels_{split}.jsonl", Path(cfg["paths"]["model_onnx_dir"]) / "model.onnx"]
    return key({"config": cfg["config_hash"],
                "files": {str(path.relative_to(cfg["root"])): digest(path) for path in paths}})


def tune(cfg):
    evaluation_dir = Path(cfg["paths"]["evaluation_dir"])
    queries = read_jsonl(evaluation_dir / "rdev.jsonl")
    qrels = read_jsonl(evaluation_dir / "qrels_dev.jsonl")
    validate_queries(queries, qrels, "dev")
    comparisons = []
    for variant in ("fixed", "structured"):
        engine = _load_engine(cfg, variant)
        for mode in cfg["retrieval"]["modes"]:
            result = evaluate(engine, queries, qrels, mode, 5)
            comparisons.append({"variant": variant, **result["metrics"]})
    complexity = {"bm25": 2, "dense": 1, "hybrid": 0}
    selected = max(comparisons, key=lambda row: (row["ndcg"], row["mrr"], row["recall"],
                                                  -row["p95_ms"], complexity[row["mode"]]))
    engine = _load_engine(cfg, selected["variant"], selected["mode"])
    k_results = [evaluate(engine, queries, qrels, selected["mode"], value)["metrics"]
                 for value in cfg["retrieval"]["final_k_candidates"]]
    chosen_k = max(k_results, key=lambda row: (row["ndcg"], row["recall"],
                                               -row["mean_context_tokens"], -row["top_k"]))["top_k"]
    threshold = choose_gate(engine, queries, cfg["gate"]["max_no_answer_false_rate"])
    engine.gate_threshold = threshold
    gated = evaluate(engine, queries, qrels, selected["mode"], chosen_k, apply_gate=True)
    value = {"schema_version": 1, "kb_release_id": cfg["kb_version"],
             "input_hash": _inputs_hash(cfg, "dev"), "selected_variant": selected["variant"],
             "selected_mode": selected["mode"], "selected_k": chosen_k,
             "gate_threshold": threshold, "comparisons": comparisons,
             "k_comparisons": k_results, "gated_metrics": gated["metrics"]}
    directory = Path(cfg["paths"]["experiment_dir"])
    directory.mkdir(parents=True, exist_ok=True)
    save(directory / "tuning.json", value)
    return value


def publish(cfg):
    experiment = Path(cfg["paths"]["experiment_dir"])
    tuning = json.loads((experiment / "tuning.json").read_text(encoding="utf-8"))
    if tuning["input_hash"] != _inputs_hash(cfg, "dev"):
        raise ValueError("Development inputs changed after tuning")
    source = Path(cfg["paths"]["work_dir"]) / tuning["selected_variant"]
    verified_manifest(source, "manifest.json")
    target = Path(cfg["paths"]["release_dir"])
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.parent / f".{target.name}.{uuid.uuid4().hex}.partial"
    try:
        (staging / "index").mkdir(parents=True)
        (staging / "model").mkdir(parents=True)
        for name in ("chunks.jsonl", "bm25.json", "dense.npy", "build.json"):
            shutil.copy2(source / name, staging / "index" / name)
        for name, path in _model_files(cfg).items():
            shutil.copy2(path, staging / "model" / name)
        cards = load_cards(cfg["paths"]["cards_dir"])
        corpus_hash = key(cards)
        components = {"chunks": "index/chunks.jsonl", "bm25": "index/bm25.json",
                      "dense": "index/dense.npy", "build": "index/build.json",
                      "model_dir": "model"}
        release = {"schema_version": 1, "kb_release_id": cfg["kb_version"],
                   "corpus_hash": corpus_hash, "index_hash": digest(staging / "index/dense.npy"),
                   "model_revision": cfg["model"]["revision"],
                   "model_hash": digest(staging / "model/model.onnx"),
                   "query_prefix": cfg["model"]["query_prefix"],
                   "max_length": cfg["model"]["max_length"], "batch_size": cfg["model"]["batch_size"],
                   "candidate_k": cfg["retrieval"]["candidate_k"],
                   "rrf_constant": cfg["retrieval"]["rrf_constant"],
                   "default_mode": tuning["selected_mode"], "default_k": tuning["selected_k"],
                   "gate_threshold": tuning["gate_threshold"],
                   "chunk_variant": tuning["selected_variant"],
                   "chunk_count": sum(1 for _ in (staging / "index/chunks.jsonl").open(encoding="utf-8")),
                   "dev_input_hash": tuning["input_hash"], "components": components}
        save(staging / "retrieval_release.json", release)
        artifacts = {str(path.relative_to(staging)).replace("\\", "/"): digest(path)
                     for path in staging.rglob("*") if path.is_file()}
        save(staging / "registry.json", {"schema_version": 1, "kb_release_id": cfg["kb_version"],
                                         "artifacts": artifacts})
        verified_manifest(staging, "registry.json")
        previous = target.parent / f".{target.name}.previous"
        if previous.exists(): shutil.rmtree(previous)
        if target.exists(): os.replace(target, previous)
        os.replace(staging, target)
        if previous.exists(): shutil.rmtree(previous)
        return verify(cfg)
    finally:
        if staging.exists(): shutil.rmtree(staging)


def finalize(cfg):
    release = verify(cfg)
    directory = Path(cfg["paths"]["experiment_dir"])
    marker = directory / "test_results.json"
    input_hash = _inputs_hash(cfg, "test")
    if marker.exists():
        existing = json.loads(marker.read_text(encoding="utf-8"))
        if existing["input_hash"] != input_hash or existing["release_hash"] != key(release):
            raise ValueError("Frozen Rtest inputs or release changed")
        return existing
    evaluation_dir = Path(cfg["paths"]["evaluation_dir"])
    queries = read_jsonl(evaluation_dir / "rtest.jsonl")
    qrels = read_jsonl(evaluation_dir / "qrels_test.jsonl")
    validate_queries(queries, qrels, "test")
    matrix = []
    for mode in cfg["retrieval"]["modes"]:
        engine = _load_engine(cfg, release["chunk_variant"], mode, 5, release["gate_threshold"])
        matrix.append({"experiment": "retriever", **evaluate(engine, queries, qrels, mode, 5)["metrics"]})
    for variant in ("fixed", "structured"):
        engine = _load_engine(cfg, variant, release["default_mode"], release["default_k"],
                              release["gate_threshold"])
        matrix.append({"experiment": "chunking", "variant": variant,
                       **evaluate(engine, queries, qrels, release["default_mode"],
                                  release["default_k"])["metrics"]})
    for top_k in cfg["retrieval"]["final_k_candidates"]:
        engine = _load_engine(cfg, release["chunk_variant"], release["default_mode"], top_k,
                              release["gate_threshold"])
        matrix.append({"experiment": "top_k", **evaluate(engine, queries, qrels,
                       release["default_mode"], top_k)["metrics"]})
    frozen = FrozenRetriever(cfg)
    gated = evaluate(frozen.engine, queries, qrels, release["default_mode"], release["default_k"],
                     apply_gate=True)
    value = {"schema_version": 1, "input_hash": input_hash, "release_hash": key(release),
             "matrix": matrix, "gated_metrics": gated["metrics"], "queries": gated["queries"]}
    save(marker, value)
    return value


def benchmark(cfg):
    """Measure the frozen retriever without reading the sealed Rtest set."""
    process = psutil.Process()
    started = time.perf_counter()
    retriever = FrozenRetriever(cfg)
    load_ms = (time.perf_counter() - started) * 1000
    queries = [row["query"] for row in read_jsonl(
        Path(cfg["paths"]["evaluation_dir"]) / "rdev.jsonl")]
    for index in range(20):
        retriever.search(queries[index % len(queries)])

    def one(index):
        before = time.perf_counter()
        result = retriever.search(queries[index % len(queries)])
        return (time.perf_counter() - before) * 1000, result["status"]

    suites = {}
    for concurrency in (1, 4):
        latencies = []
        errors = 0
        suite_started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [pool.submit(one, index) for index in range(100)]
            for future in as_completed(futures):
                try:
                    latency, _status = future.result()
                    latencies.append(latency)
                except Exception:
                    errors += 1
        ordered = sorted(latencies)
        p95_index = max(0, int(np.ceil(len(ordered) * 0.95)) - 1)
        suites[str(concurrency)] = {
            "requests": 100,
            "errors": errors,
            "p50_ms": statistics.median(ordered) if ordered else None,
            "p95_ms": ordered[p95_index] if ordered else None,
            "throughput_qps": 100 / max(time.perf_counter() - suite_started, 1e-9),
        }
    result = {
        "schema_version": 1,
        "release_id": retriever.manifest["kb_release_id"],
        "load_ms": load_ms,
        "rss_bytes": process.memory_info().rss,
        "warmup_requests": 20,
        "concurrency": suites,
    }
    output = Path(cfg["paths"]["experiment_dir"]) / "benchmark.json"
    save(output, result)
    return result
