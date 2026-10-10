import copy
import csv
import json
import math
import subprocess
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import joblib
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import torch
from drain3.file_persistence import FilePersistence
from drain3.template_miner import TemplateMiner
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from aiops_diag.data.common import digest, key, save, verified_manifest
from aiops_diag.modeling.lstm_model import resolve_device
from aiops_diag.modeling.lstm_workflow import (
    _load_data, _make_loader, _score, _train_once, _verify_run,
    load_registered_model, train_lstm,
)
from aiops_diag.modeling.metrics import classification_metrics, select_threshold
from aiops_diag.modeling.models import _document, _load_rows, load_registered, train
from aiops_diag.modeling.templates import content, miner_config


UNIFIED_SCHEMA = pa.schema([
    ("model_id", pa.string()), ("model_family", pa.string()), ("seed", pa.int32()),
    ("split", pa.string()), ("block_id", pa.string()), ("sampling_group", pa.string()),
    ("label", pa.int8()), ("anomaly_score", pa.float64()), ("threshold", pa.float64()),
    ("prediction", pa.int8()), ("first_log_id", pa.string()), ("last_log_id", pa.string()),
    ("line_count", pa.int32()),
])

TEST_FEATURE_SCHEMA = pa.schema([
    ("block_id", pa.string()), ("split", pa.string()), ("sampling_group", pa.string()),
    ("template_ids", pa.list_(pa.int32())), ("gap_seconds", pa.list_(pa.float32())),
    ("line_count", pa.int32()), ("warn_count", pa.int32()), ("error_count", pa.int32()),
    ("start_time", pa.string()), ("end_time", pa.string()), ("duration_seconds", pa.float64()),
    ("first_log_id", pa.string()), ("last_log_id", pa.string()), ("unknown_count", pa.int32()),
])


def _git_commit(root):
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True,
                              capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _stage(directory, manifest_name):
    directory = Path(directory)
    verified_manifest(directory, "registry.json")
    return verified_manifest(directory, manifest_name)


def _publish_stage(directory, manifest_name, details, filenames):
    directory = Path(directory)
    details = {**details, "artifacts": {name: digest(directory / name) for name in filenames}}
    save(directory / manifest_name, details)
    save(directory / "registry.json", {
        "schema_version": 1, "artifacts": {manifest_name: digest(directory / manifest_name)}})
    return _stage(directory, manifest_name)


def _runs(cfg):
    w2 = train(cfg["w2"])
    w3 = train_lstm(cfg["lstm"], cfg["runtime"]["device"])
    return w2, w3


def _assignments(cfg):
    path = Path(cfg["w2"]["protocol_dir"]) / "assignments.parquet"
    return {row["block_id"]: row for row in pq.read_table(path).to_pylist()}


def _validation_predictions(cfg, w2, w3, output):
    assignment = _assignments(cfg)
    w2_rows = pq.read_table(Path(w2["run_dir"]) / "predictions.parquet").to_pylist()
    w3_rows = pq.read_table(Path(w3["run_dir"]) / "predictions.parquet").to_pylist()
    thresholds = {"logistic_regression": w2["thresholds"]["logistic_regression"]}
    w3_results = _read(Path(w3["run_dir"]) / "results.json")
    for row in w3_results["seeds"]:
        thresholds[f"lstm_seed_{row['seed']}"] = row["metrics"]["threshold"]
    lines = {row["block_id"]: row["line_count"] for row in w2_rows}
    unified = []
    for row in w2_rows:
        unified.append({
            "model_id": "logistic_regression", "model_family": "tfidf_lr", "seed": 42,
            "split": "validation", "block_id": row["block_id"],
            "sampling_group": assignment[row["block_id"]]["sampling_group"],
            "label": row["label"], "anomaly_score": row["logistic_regression_score"],
            "threshold": thresholds["logistic_regression"],
            "prediction": row["logistic_regression_prediction"],
            "first_log_id": row["first_log_id"], "last_log_id": row["last_log_id"],
            "line_count": row["line_count"],
        })
    for row in w3_rows:
        model_id = f"lstm_seed_{row['seed']}"
        unified.append({
            "model_id": model_id, "model_family": "lstm", "seed": row["seed"],
            "split": "validation", "block_id": row["block_id"],
            "sampling_group": assignment[row["block_id"]]["sampling_group"],
            "label": row["label"], "anomaly_score": row["anomaly_score"],
            "threshold": thresholds[model_id], "prediction": row["prediction"],
            "first_log_id": row["first_log_id"], "last_log_id": row["last_log_id"],
            "line_count": lines[row["block_id"]],
        })
    expected = len(w2_rows)
    counts = defaultdict(int)
    memberships = defaultdict(set)
    for row in unified:
        counts[row["model_id"]] += 1
        memberships[row["model_id"]].add(row["block_id"])
    if set(counts) != set(cfg["allowed_test_models"]):
        raise ValueError("Validation model set differs from preregistered candidates")
    if any(value != expected for value in counts.values()):
        raise ValueError("Validation prediction counts are not aligned")
    reference = memberships["logistic_regression"]
    if any(value != reference for value in memberships.values()):
        raise ValueError("Validation prediction memberships are not aligned")
    pq.write_table(pa.Table.from_pylist(unified, schema=UNIFIED_SCHEMA), output,
                   compression="zstd")
    return counts, thresholds


def _selection_decision(w2, w3, cfg):
    lr = _read(Path(w2["run_dir"]) / "results.json")["logistic_regression"]["metrics"]
    lstm = _read(Path(w3["run_dir"]) / "results.json")
    seed_metrics = [row["metrics"] for row in lstm["seeds"]]
    mean_f1 = float(np.mean([row["f1"] for row in seed_metrics]))
    improvement = mean_f1 - lr["f1"]
    strict_better = sum(row["fp"] < lr["fp"] and row["fn"] < lr["fn"]
                        for row in seed_metrics)
    eligible = improvement >= cfg["selection"]["lstm_min_f1_improvement"] or \
        strict_better >= cfg["selection"]["lstm_min_seeds_reducing_fp_and_fn"]
    return {
        "frozen_before_test": True,
        "default_model": "lstm" if eligible else "logistic_regression",
        "research_model": "logistic_regression" if eligible else "lstm",
        "reason": "LSTM met preregistered validation promotion rule" if eligible else
                  "Validation gain was below the preregistered materiality rule; prefer LR simplicity",
        "validation": {"lr_f1": lr["f1"], "lstm_mean_f1": mean_f1,
                       "lstm_f1_improvement": improvement,
                       "lstm_seeds_reducing_both_fp_and_fn": strict_better},
        "rule": cfg["selection"],
        "test_may_not_change_selection": True,
    }


def preregister(cfg):
    out = Path(cfg["experiment_dir"]) / "preregister"
    if (out / "manifest.json").exists():
        value = _stage(out, "manifest.json")
        if value["config_hash"] != cfg["config_hash"]:
            raise ValueError("W4 preregistration belongs to a different configuration")
        w2, w3 = _runs(cfg)
        current = {
            "data_membership_hash": verified_manifest(
                cfg["w2"]["protocol_dir"], "manifest.json")["membership_hash"],
            "w2_training_hash": digest(Path(w2["run_dir"]) / "training.json"),
            "w3_training_hash": digest(Path(w3["run_dir"]) / "training.json"),
        }
        if current != value["upstream"]:
            raise ValueError("A preregistered upstream artifact changed")
        return {**value, "directory": str(out)}
    w2, w3 = _runs(cfg)
    out.mkdir(parents=True, exist_ok=True)
    counts, thresholds = _validation_predictions(cfg, w2, w3,
                                                 out / "validation_predictions.parquet")
    decision = _selection_decision(w2, w3, cfg)
    save(out / "selection_decision.json", decision)
    protocol = verified_manifest(cfg["w2"]["protocol_dir"], "manifest.json")
    details = {
        "schema_version": 1, "protocol": cfg["protocol_name"],
        "config_hash": cfg["config_hash"], "git_commit": _git_commit(cfg["root"]),
        "created_before_test_evaluation": True,
        "allowed_test_models": cfg["allowed_test_models"],
        "validation_counts": dict(counts), "frozen_thresholds": thresholds,
        "selection_decision_hash": digest(out / "selection_decision.json"),
        "upstream": {
            "data_membership_hash": protocol["membership_hash"],
            "w2_training_hash": digest(Path(w2["run_dir"]) / "training.json"),
            "w3_training_hash": digest(Path(w3["run_dir"]) / "training.json"),
        },
        "test_status": "sealed; no W4 test prediction or metric exists",
    }
    value = _publish_stage(out, "manifest.json", details,
                           ["validation_predictions.parquet", "selection_decision.json"])
    return {**value, "directory": str(out)}


def _fit_lr(x_train, y_train, x_validation, y_validation, cfg):
    runs = []
    models = {}
    scores = {}
    for c_value in cfg["parsing_comparison"]["c_values"]:
        for weight_name in cfg["parsing_comparison"]["class_weights"]:
            class_weight = None if weight_name == "none" else weight_name
            for seed in cfg["lstm"]["seeds"]:
                model = LogisticRegression(C=float(c_value), class_weight=class_weight,
                                           solver="liblinear", max_iter=1000,
                                           random_state=seed).fit(x_train, y_train)
                value = model.decision_function(x_validation)
                metrics, _ = select_threshold(y_validation, value,
                                              cfg["selection"]["max_fpr"])
                runs.append({"c": float(c_value), "class_weight": weight_name,
                             "seed": seed, "metrics": metrics})
                models[(float(c_value), weight_name, seed)] = model
                scores[(float(c_value), weight_name, seed)] = value
    grouped = defaultdict(list)
    for row in runs:
        grouped[(row["c"], row["class_weight"])].append(row)
    ranked = []
    for (c_value, weight_name), values in grouped.items():
        ranked.append({"c": c_value, "class_weight": weight_name,
                       "mean_f1": float(np.mean([r["metrics"]["f1"] for r in values])),
                       "mean_ap": float(np.mean([r["metrics"]["average_precision"]
                                                  for r in values]))})
    selected = max(ranked, key=lambda row: (row["mean_f1"], row["mean_ap"], -row["c"],
                                             row["class_weight"] == "none"))
    identity = (selected["c"], selected["class_weight"], cfg["lstm"]["seed"])
    return models[identity], scores[identity], selected, runs


def _raw_documents(cfg, rows):
    wanted = {row["block_id"] for row in rows}
    pieces = {block: [] for block in wanted}
    columns = ["level", "component", "message", "session_ids"]
    for batch in pq.ParquetFile(Path(cfg["w2"]["w1_dir"]) / "logs.parquet").iter_batches(
            columns=columns, batch_size=50000):
        for row in batch.to_pylist():
            selected = [block for block in row["session_ids"] if block in wanted]
            if not selected:
                continue
            redacted = content(row)
            for block in selected:
                pieces[block].append(redacted)
    documents = []
    for row in rows:
        values = pieces[row["block_id"]]
        if not values:
            raise ValueError(f"No redacted messages for {row['block_id']}")
        documents.append("\n".join(values))
    return documents


def compare_parsing(cfg):
    preregister(cfg)
    out = Path(cfg["experiment_dir"]) / "parsing_comparison"
    if (out / "manifest.json").exists():
        value = _stage(out, "manifest.json")
        if value["config_hash"] != cfg["config_hash"]:
            raise ValueError("Parsing comparison configuration changed")
        return {**value, "directory": str(out)}
    started = time.monotonic()
    train_rows, validation_rows = _load_rows(cfg["w2"])
    y_train = np.asarray([row["label"] for row in train_rows], dtype=np.int8)
    y_validation = np.asarray([row["label"] for row in validation_rows], dtype=np.int8)
    template_vectorizer = load_registered(cfg["w2"], "tfidf.joblib")
    x_template_train = template_vectorizer.transform([_document(row) for row in train_rows])
    x_template_validation = template_vectorizer.transform([_document(row) for row in validation_rows])
    safe_train = np.asarray([[np.log1p(row["line_count"]),
                              np.log1p(max(0.0, row["duration_seconds"])),
                              row["warn_count"] / max(1, row["line_count"]),
                              row["error_count"] / max(1, row["line_count"])]
                             for row in train_rows], dtype=np.float32)
    safe_validation = np.asarray([[np.log1p(row["line_count"]),
                                   np.log1p(max(0.0, row["duration_seconds"])),
                                   row["warn_count"] / max(1, row["line_count"]),
                                   row["error_count"] / max(1, row["line_count"])]
                                  for row in validation_rows], dtype=np.float32)
    means, stds = safe_train.mean(axis=0), safe_train.std(axis=0)
    stds[stds == 0] = 1
    safe_train = (safe_train - means) / stds
    safe_validation = (safe_validation - means) / stds
    x_plus_train = sparse.hstack([x_template_train, sparse.csr_matrix(safe_train)], format="csr")
    x_plus_validation = sparse.hstack([x_template_validation,
                                       sparse.csr_matrix(safe_validation)], format="csr")

    raw_documents = _raw_documents(cfg, train_rows + validation_rows)
    raw_vectorizer = TfidfVectorizer(tokenizer=str.split, token_pattern=None, lowercase=False,
                                     ngram_range=(1, 1), dtype=np.float32,
                                     max_features=cfg["parsing_comparison"]["max_features"],
                                     min_df=cfg["parsing_comparison"]["min_df"])
    x_raw_train = raw_vectorizer.fit_transform(raw_documents[:len(train_rows)])
    x_raw_validation = raw_vectorizer.transform(raw_documents[len(train_rows):])
    representations = {
        "redacted_text": (x_raw_train, x_raw_validation),
        "template_unigram": (x_template_train, x_template_validation),
        "template_plus_safe": (x_plus_train, x_plus_validation),
    }
    out.mkdir(parents=True, exist_ok=True)
    results = {}
    prediction_rows = []
    for name, (x_train, x_validation) in representations.items():
        before = time.monotonic()
        model, scores, selected, runs = _fit_lr(x_train, y_train, x_validation,
                                                y_validation, cfg)
        metrics, _ = select_threshold(y_validation, scores, cfg["selection"]["max_fpr"])
        prediction = (scores >= metrics["threshold"]).astype(np.int8)
        results[name] = {"selected": selected, "metrics": metrics,
                         "grid_runs": runs, "feature_count": int(x_train.shape[1]),
                         "train_nonzero": int(x_train.nnz),
                         "elapsed_seconds": time.monotonic() - before}
        joblib.dump(model, out / f"{name}_lr.joblib", compress=3)
        for index, row in enumerate(validation_rows):
            prediction_rows.append({"representation": name, "block_id": row["block_id"],
                                    "label": int(y_validation[index]),
                                    "anomaly_score": float(scores[index]),
                                    "prediction": int(prediction[index])})
    joblib.dump(raw_vectorizer, out / "redacted_text_tfidf.joblib", compress=3)
    save(out / "safe_scaler.json", {"mean": means.tolist(), "std": stds.tolist(),
                                     "fit_split": "Dmain only"})
    save(out / "results.json", results)
    pq.write_table(pa.Table.from_pylist(prediction_rows), out / "predictions.parquet",
                   compression="zstd")
    files = ["results.json", "predictions.parquet", "safe_scaler.json",
             "redacted_text_tfidf.joblib", "redacted_text_lr.joblib",
             "template_unigram_lr.joblib", "template_plus_safe_lr.joblib"]
    details = {"schema_version": 1, "config_hash": cfg["config_hash"],
               "train_sessions": len(train_rows), "validation_sessions": len(validation_rows),
               "representations": list(representations), "test_accessed": False,
               "forbidden_features": ["label", "block_id", "ip", "pid", "path", "raw_number"],
               "elapsed_seconds": time.monotonic() - started}
    value = _publish_stage(out, "manifest.json", details, files)
    return {**value, "directory": str(out)}


def _variant_rows(rows, variant, cfg):
    if variant != "no_order_no_gap":
        return rows
    transformed = []
    for row in rows:
        value = dict(row)
        order = sorted(range(len(row["template_ids"])), key=lambda index: key([
            "w4_shuffle", cfg["ablation"]["shuffle_seed"], row["block_id"], index]))
        value["template_ids"] = [row["template_ids"][index] for index in order]
        neutral_gap = cfg["ablation"].get("neutral_gap_seconds", 0.0)
        value["gap_seconds"] = [neutral_gap] * len(order)
        transformed.append(value)
    return transformed


def _ablation_variant(cfg, variant, rows, labels, scaler, device):
    out = Path(cfg["experiment_dir"]) / "ablations" / variant
    if (out / "manifest.json").exists():
        return _stage(out, "manifest.json")
    local_cfg = copy.deepcopy(cfg["lstm"])
    session_features = 4
    if variant == "max_len_32":
        local_cfg["features"]["max_length"] = 32
    elif variant == "max_len_64":
        local_cfg["features"]["max_length"] = 64
    elif variant == "no_safe_features":
        session_features = 0
    elif variant != "no_order_no_gap":
        raise ValueError(f"Unknown ablation variant: {variant}")
    transform_cfg = copy.deepcopy(cfg)
    if variant == "no_order_no_gap":
        # SequenceDataset standardizes log1p(gap); this inverse value becomes
        # exactly zero after the frozen training scaler and therefore removes
        # interval information without refitting the scaler.
        transform_cfg["ablation"]["neutral_gap_seconds"] = math.expm1(scaler["gap"]["mean"])
    fit = _variant_rows([row for row in rows if row["dmain_role"] == "fit"], variant,
                        transform_cfg)
    stop = _variant_rows([row for row in rows if row["dmain_role"] == "holdout"], variant,
                         transform_cfg)
    validation = _variant_rows([row for row in rows if row["split"] == "validation"],
                               variant, transform_cfg)
    out.mkdir(parents=True, exist_ok=True)
    results, histories, predictions, checkpoints = [], {}, [], []
    for seed in cfg["lstm"]["seeds"]:
        model, audit = _train_once(fit, stop, labels, scaler, local_cfg, 64, "one",
                                   seed, device, session_feature_count=session_features)
        name = f"{variant}_seed_{seed}.pt"
        torch.save(model.state_dict(), out / name)
        checkpoints.append(name)
        loader = _make_loader(validation, labels, scaler, local_cfg, False, seed)
        y, scores, records = _score(model, loader, device)
        metrics, _ = select_threshold(y, scores, cfg["selection"]["max_fpr"])
        predicted = (scores >= metrics["threshold"]).astype(np.int8)
        results.append({"variant": variant, "seed": seed, "metrics": metrics,
                        "best_epoch": audit["best_epoch"], "resource": audit["resource"]})
        histories[str(seed)] = audit
        predictions.extend({"variant": variant, "seed": seed,
                            "block_id": record["block_id"], "label": int(y[index]),
                            "anomaly_score": float(scores[index]),
                            "prediction": int(predicted[index])}
                           for index, record in enumerate(records))
        if device.type == "cuda":
            torch.cuda.empty_cache()
    save(out / "results.json", results)
    save(out / "histories.json", histories)
    pq.write_table(pa.Table.from_pylist(predictions), out / "predictions.parquet",
                   compression="zstd")
    files = ["results.json", "histories.json", "predictions.parquet", *checkpoints]
    return _publish_stage(out, "manifest.json", {
        "schema_version": 1, "variant": variant, "config_hash": cfg["config_hash"],
        "seeds": cfg["lstm"]["seeds"], "train_sessions": len(fit),
        "early_stop_sessions": len(stop), "validation_sessions": len(validation),
        "max_length": local_cfg["features"]["max_length"],
        "session_feature_count": session_features, "test_accessed": False,
    }, files)


def ablate(cfg, device_name="auto"):
    preregister(cfg)
    _, rows, labels, scaler = _load_data(cfg["lstm"])
    device = resolve_device(device_name)
    manifests = {}
    for variant in cfg["ablation"]["variants"]:
        manifests[variant] = _ablation_variant(cfg, variant, rows, labels, scaler, device)
    out = Path(cfg["experiment_dir"]) / "ablations"
    w3 = train_lstm(cfg["lstm"], device_name)
    full = _read(Path(w3["run_dir"]) / "results.json")
    rows_out = []
    for row in full["seeds"]:
        rows_out.append({"variant": "full", "seed": row["seed"], **row["metrics"]})
    for variant in cfg["ablation"]["variants"]:
        values = _read(out / variant / "results.json")
        rows_out.extend({"variant": variant, "seed": row["seed"], **row["metrics"]}
                        for row in values)
    full_by_seed = {row["seed"]: row for row in rows_out if row["variant"] == "full"}
    for row in rows_out:
        baseline = full_by_seed[row["seed"]]
        row["delta_f1_vs_full"] = row["f1"] - baseline["f1"]
        row["delta_ap_vs_full"] = row["average_precision"] - baseline["average_precision"]
    save(out / "summary.json", rows_out)
    with (out / "summary.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows_out[0]))
        writer.writeheader(); writer.writerows(rows_out)
    files = ["summary.json", "summary.csv"]
    details = {"schema_version": 1, "config_hash": cfg["config_hash"],
               "variants": ["full", *cfg["ablation"]["variants"]],
               "validation_only": True, "test_accessed": False,
               "variant_manifest_hashes": {name: digest(out / name / "manifest.json")
                                            for name in cfg["ablation"]["variants"]}}
    value = _publish_stage(out, "manifest.json", details, files)
    return {**value, "directory": str(out)}


def _test_features(cfg):
    out = Path(cfg["artifact_dir"]) / "test_features"
    if (out / "manifest.json").exists():
        return _stage(out, "manifest.json")
    preregister(cfg)
    assignment = _assignments(cfg)
    selected = {block: row for block, row in assignment.items() if row["split"] == "test"}
    states = {block: {"template_ids": [], "gap_seconds": [], "line_count": 0,
                      "warn_count": 0, "error_count": 0, "start": None, "end": None,
                      "first_log_id": None, "last_log_id": None, "unknown_count": 0,
                      "previous": None} for block in selected}
    snapshot = Path(cfg["w2"]["artifact_dir"]) / "drain3_state.bin"
    template_manifest = verified_manifest(cfg["w2"]["artifact_dir"], "templates.json")
    before_hash = digest(snapshot)
    miner = TemplateMiner(FilePersistence(str(snapshot)),
                          miner_config(cfg["w2"], template_manifest["selected_similarity"]))
    messages = unknown_messages = negative_gaps = 0
    columns = ["log_id", "timestamp_local", "level", "component", "message", "session_ids"]
    for batch in pq.ParquetFile(Path(cfg["w2"]["w1_dir"]) / "logs.parquet").iter_batches(
            columns=columns, batch_size=50000):
        for row in batch.to_pylist():
            members = [block for block in row["session_ids"] if block in selected]
            if not members:
                continue
            cluster = miner.match(content(row), full_search_strategy="always")
            unknown = cluster is None
            template_id = 0 if unknown else int(cluster.cluster_id)
            stamp = datetime.fromisoformat(row["timestamp_local"])
            for block in members:
                state = states[block]
                delta = 0.0 if state["previous"] is None else \
                    (stamp - state["previous"]).total_seconds()
                if delta < 0:
                    negative_gaps += 1
                    delta = 0.0
                state["template_ids"].append(template_id)
                state["gap_seconds"].append(float(delta))
                state["line_count"] += 1
                state["warn_count"] += row["level"] == "WARN"
                state["error_count"] += row["level"] == "ERROR"
                state["start"] = min(state["start"] or row["timestamp_local"], row["timestamp_local"])
                state["end"] = max(state["end"] or row["timestamp_local"], row["timestamp_local"])
                state["first_log_id"] = state["first_log_id"] or row["log_id"]
                state["last_log_id"] = row["log_id"]
                state["unknown_count"] += int(unknown)
                state["previous"] = stamp
            messages += 1
            unknown_messages += int(unknown)
    after_hash = digest(snapshot)
    if before_hash != after_hash:
        raise ValueError("Frozen Drain3 snapshot changed during W4 test matching")
    if any(not state["line_count"] for state in states.values()):
        raise ValueError("At least one test session has no matched source log")
    out.mkdir(parents=True, exist_ok=True)
    writer = pq.ParquetWriter(out / "sessions.parquet", TEST_FEATURE_SCHEMA,
                              compression="zstd")
    buffer = []
    for block in sorted(states):
        state = states[block]
        duration = (datetime.fromisoformat(state["end"]) -
                    datetime.fromisoformat(state["start"])).total_seconds()
        buffer.append({"block_id": block, "split": "test",
                       "sampling_group": selected[block]["sampling_group"],
                       "template_ids": state["template_ids"],
                       "gap_seconds": state["gap_seconds"], "line_count": state["line_count"],
                       "warn_count": state["warn_count"], "error_count": state["error_count"],
                       "start_time": state["start"], "end_time": state["end"],
                       "duration_seconds": duration, "first_log_id": state["first_log_id"],
                       "last_log_id": state["last_log_id"],
                       "unknown_count": state["unknown_count"]})
        if len(buffer) == 10000:
            writer.write_table(pa.Table.from_pylist(buffer, schema=TEST_FEATURE_SCHEMA)); buffer = []
    if buffer:
        writer.write_table(pa.Table.from_pylist(buffer, schema=TEST_FEATURE_SCHEMA))
    writer.close()
    return _publish_stage(out, "manifest.json", {
        "schema_version": 1, "config_hash": cfg["config_hash"], "sessions": len(states),
        "messages": messages, "unknown_messages": unknown_messages,
        "unknown_rate": unknown_messages / messages if messages else None,
        "negative_gaps_clamped": negative_gaps, "drain_snapshot_hash": before_hash,
        "labels_accessed": False,
    }, ["sessions.parquet"])


def _test_labels(cfg):
    path = Path(cfg["w2"]["data"]["raw_dir"]) / "anomaly_label.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {row["BlockId"]: 1 if row["Label"] == "Anomaly" else 0
                for row in csv.DictReader(handle)}


def _unified_metrics(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["model_id"]].append(row)
    return {name: classification_metrics([row["label"] for row in values],
                                         [row["prediction"] for row in values],
                                         [row["anomaly_score"] for row in values])
            for name, values in grouped.items()}


def _weighted_ap(labels, scores, weights):
    order = np.argsort(-scores, kind="stable")
    y = labels[order]
    s = scores[order]
    w = weights[order]
    starts = np.r_[0, np.flatnonzero(s[1:] != s[:-1]) + 1]
    positive = np.add.reduceat(w * y, starts)
    total = np.add.reduceat(w, starts)
    total_positive = positive.sum()
    if total_positive <= 0:
        return None
    cumulative_positive = np.cumsum(positive)
    cumulative_total = np.cumsum(total)
    precision = np.divide(cumulative_positive, cumulative_total,
                          out=np.zeros_like(cumulative_positive, dtype=np.float64),
                          where=cumulative_total > 0)
    return float(np.sum((positive / total_positive) * precision))


def _ap_plan(labels, scores):
    order = np.argsort(-scores, kind="stable")
    sorted_scores = scores[order]
    return order, labels[order], np.r_[0, np.flatnonzero(
        sorted_scores[1:] != sorted_scores[:-1]) + 1]


def _planned_weighted_ap(plan, weights):
    order, labels, starts = plan
    ordered_weights = weights[order]
    positive = np.add.reduceat(ordered_weights * labels, starts)
    total = np.add.reduceat(ordered_weights, starts)
    total_positive = positive.sum()
    if total_positive <= 0:
        return None
    cumulative_positive = np.cumsum(positive)
    cumulative_total = np.cumsum(total)
    precision = np.divide(cumulative_positive, cumulative_total,
                          out=np.zeros_like(cumulative_positive, dtype=np.float64),
                          where=cumulative_total > 0)
    return float(np.sum((positive / total_positive) * precision))


def paired_bootstrap(rows, cfg):
    by_model = defaultdict(dict)
    groups = {}
    labels = {}
    for row in rows:
        by_model[row["model_id"]][row["block_id"]] = row
        groups[row["block_id"]] = row["sampling_group"]
        labels[row["block_id"]] = row["label"]
    blocks = sorted(by_model["logistic_regression"])
    if set(blocks) != set(by_model["lstm_seed_42"]):
        raise ValueError("Paired bootstrap model memberships differ")
    unique_groups = sorted(set(groups.values()))
    group_index = {value: index for index, value in enumerate(unique_groups)}
    row_group = np.asarray([group_index[groups[block]] for block in blocks], dtype=np.int32)
    y = np.asarray([labels[block] for block in blocks], dtype=np.int8)
    lr = by_model["logistic_regression"]
    nn = by_model["lstm_seed_42"]
    lr_scores = np.asarray([lr[block]["anomaly_score"] for block in blocks])
    nn_scores = np.asarray([nn[block]["anomaly_score"] for block in blocks])
    lr_predictions = np.asarray([lr[block]["prediction"] for block in blocks], dtype=np.int8)
    nn_predictions = np.asarray([nn[block]["prediction"] for block in blocks], dtype=np.int8)
    lr_ap_plan = _ap_plan(y, lr_scores)
    nn_ap_plan = _ap_plan(y, nn_scores)
    rng = np.random.default_rng(cfg["bootstrap"]["seed"])
    delta_f1, delta_ap = [], []

    def weighted_f1(prediction, weights):
        tp = float(weights[(y == 1) & (prediction == 1)].sum())
        fp = float(weights[(y == 0) & (prediction == 1)].sum())
        fn = float(weights[(y == 1) & (prediction == 0)].sum())
        denominator = 2 * tp + fp + fn
        return 2 * tp / denominator if denominator else 0.0

    for _ in range(cfg["bootstrap"]["replicates"]):
        group_weights = rng.poisson(1.0, len(unique_groups)).astype(np.float64)
        weights = group_weights[row_group]
        if weights[y == 1].sum() == 0 or weights[y == 0].sum() == 0:
            continue
        delta_f1.append(weighted_f1(nn_predictions, weights) -
                        weighted_f1(lr_predictions, weights))
        delta_ap.append(_planned_weighted_ap(nn_ap_plan, weights) -
                        _planned_weighted_ap(lr_ap_plan, weights))
    return {
        "method": cfg["bootstrap"]["method"], "sampling_unit": "sampling_group",
        "representative_lstm": "lstm_seed_42", "baseline": "logistic_regression",
        "seed": cfg["bootstrap"]["seed"], "requested_replicates": cfg["bootstrap"]["replicates"],
        "valid_replicates": len(delta_f1),
        "delta_f1": {"mean": float(np.mean(delta_f1)),
                     "ci95": np.percentile(delta_f1, [2.5, 97.5]).tolist()},
        "delta_ap": {"mean": float(np.mean(delta_ap)),
                     "ci95": np.percentile(delta_ap, [2.5, 97.5]).tolist()},
    }


def _failure_cases(rows):
    by_model = defaultdict(list)
    for row in rows:
        by_model[row["model_id"]].append(row)
    result = {}
    for model, values in by_model.items():
        result[model] = {
            "highest_false_positives": sorted(
                (row for row in values if row["label"] == 0 and row["prediction"] == 1),
                key=lambda row: (-row["anomaly_score"], row["block_id"]))[:10],
            "lowest_false_negatives": sorted(
                (row for row in values if row["label"] == 1 and row["prediction"] == 0),
                key=lambda row: (row["anomaly_score"], row["block_id"]))[:10],
        }
    lr = {row["block_id"]: row for row in by_model["logistic_regression"]}
    nn = {row["block_id"]: row for row in by_model["lstm_seed_42"]}
    disagreements = [{"block_id": block, "label": lr[block]["label"],
                      "lr_prediction": lr[block]["prediction"],
                      "lr_score": lr[block]["anomaly_score"],
                      "lstm_prediction": nn[block]["prediction"],
                      "lstm_score": nn[block]["anomaly_score"],
                      "first_log_id": lr[block]["first_log_id"],
                      "last_log_id": lr[block]["last_log_id"]}
                     for block in lr if lr[block]["prediction"] != nn[block]["prediction"]]
    result["lr_vs_lstm_seed_42_disagreements"] = disagreements[:100]
    result["disagreement_count"] = len(disagreements)
    return result


def finalize(cfg, device_name="auto"):
    prereg = preregister(cfg)
    out = Path(cfg["experiment_dir"]) / "final"
    if (out / "manifest.json").exists():
        value = _stage(out, "manifest.json")
        test_manifest = _stage(Path(cfg["artifact_dir"]) / "test_features", "manifest.json")
        if value["config_hash"] != cfg["config_hash"] or \
                value["preregister_hash"] != digest(Path(prereg["directory"]) / "manifest.json") or \
                value["test_feature_hash"] != key(test_manifest["artifacts"]):
            raise ValueError("Frozen W4 final result cannot be reused with changed inputs")
        return {**value, "directory": str(out)}
    test_manifest = _test_features(cfg)
    test_rows = pq.read_table(Path(cfg["artifact_dir"]) / "test_features" /
                              "sessions.parquet").to_pylist()
    labels = _test_labels(cfg)
    if set(row["block_id"] for row in test_rows) - set(labels):
        raise ValueError("Some test sessions do not have labels")
    frozen_thresholds = prereg["frozen_thresholds"]
    unified = []

    vectorizer = load_registered(cfg["w2"], "tfidf.joblib")
    lr_model = load_registered(cfg["w2"], "logistic_regression.joblib")
    lr_scores = lr_model.decision_function(vectorizer.transform([_document(row) for row in test_rows]))
    lr_threshold = frozen_thresholds["logistic_regression"]
    lr_predictions = (lr_scores >= lr_threshold).astype(np.int8)
    for index, row in enumerate(test_rows):
        unified.append({"model_id": "logistic_regression", "model_family": "tfidf_lr",
                        "seed": 42, "split": "test", "block_id": row["block_id"],
                        "sampling_group": row["sampling_group"], "label": labels[row["block_id"]],
                        "anomaly_score": float(lr_scores[index]), "threshold": lr_threshold,
                        "prediction": int(lr_predictions[index]),
                        "first_log_id": row["first_log_id"], "last_log_id": row["last_log_id"],
                        "line_count": row["line_count"]})

    scaler = _read(Path(cfg["lstm"]["feature_dir"]) / "scaler.json")
    sequence_rows = [{"block_id": row["block_id"], "template_ids": [v + 1 for v in row["template_ids"]],
                      "gap_seconds": row["gap_seconds"], "session_length": row["line_count"],
                      "duration_seconds": row["duration_seconds"],
                      "warn_ratio": row["warn_count"] / max(1, row["line_count"]),
                      "error_ratio": row["error_count"] / max(1, row["line_count"]),
                      "first_log_id": row["first_log_id"], "last_log_id": row["last_log_id"]}
                     for row in test_rows]
    w3 = train_lstm(cfg["lstm"], device_name)
    for seed in cfg["lstm"]["seeds"]:
        model, device = load_registered_model(cfg["lstm"], w3["run_id"], seed, device_name)
        loader = _make_loader(sequence_rows, labels, scaler, cfg["lstm"], False, seed)
        y, scores, records = _score(model, loader, device)
        model_id = f"lstm_seed_{seed}"
        threshold = frozen_thresholds[model_id]
        predictions = (scores >= threshold).astype(np.int8)
        metadata = {row["block_id"]: row for row in test_rows}
        for index, record in enumerate(records):
            row = metadata[record["block_id"]]
            unified.append({"model_id": model_id, "model_family": "lstm", "seed": seed,
                            "split": "test", "block_id": record["block_id"],
                            "sampling_group": row["sampling_group"], "label": int(y[index]),
                            "anomaly_score": float(scores[index]), "threshold": threshold,
                            "prediction": int(predictions[index]),
                            "first_log_id": record["first_log_id"],
                            "last_log_id": record["last_log_id"],
                            "line_count": row["line_count"]})
        if device.type == "cuda":
            torch.cuda.empty_cache()
    counts = defaultdict(int)
    for row in unified:
        counts[row["model_id"]] += 1
    if set(counts) != set(cfg["allowed_test_models"]) or \
            any(count != len(test_rows) for count in counts.values()):
        raise ValueError("Final model membership does not match preregistration")
    out.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(unified, schema=UNIFIED_SCHEMA),
                   out / "predictions.parquet", compression="zstd")
    metrics = _unified_metrics(unified)
    save(out / "metrics.json", metrics)
    uncertainty = paired_bootstrap(unified, cfg)
    save(out / "uncertainty.json", uncertainty)
    failures = _failure_cases(unified)
    save(out / "failure_cases.json", failures)
    decision = _read(Path(prereg["directory"]) / "selection_decision.json")
    release = {
        "schema_version": 1, "release": "v0.2", "protocol": cfg["protocol_name"],
        "default_model": decision["default_model"], "research_model": decision["research_model"],
        "selection_frozen_before_test": True, "test_did_not_change_selection": True,
        "test_sessions": len(test_rows), "test_anomalies": sum(labels[row["block_id"]]
                                                                  for row in test_rows),
        "thresholds": frozen_thresholds, "models": cfg["allowed_test_models"],
        "upstream": {"preregister": digest(Path(prereg["directory"]) / "manifest.json"),
                     "test_features": key(test_manifest["artifacts"]),
                     "w3_training": digest(Path(w3["run_dir"]) / "training.json")},
        "limitations": ["164 exact template sequences overlap train/validation",
                        "HDFS labels are block anomaly labels, not root-cause classes",
                        "No trustworthy fault start time; no production MTTD is reported"],
    }
    save(out / "release_manifest.json", release)
    rows_csv = []
    for model, value in metrics.items():
        rows_csv.append({"model_id": model, **value})
    with (out / "algorithm_table.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows_csv[0]))
        writer.writeheader(); writer.writerows(rows_csv)
    save(out / "algorithm_table.json", rows_csv)
    files = ["predictions.parquet", "metrics.json", "uncertainty.json",
             "failure_cases.json", "release_manifest.json", "algorithm_table.csv",
             "algorithm_table.json"]
    value = _publish_stage(out, "manifest.json", {
        "schema_version": 1, "config_hash": cfg["config_hash"],
        "preregister_hash": digest(Path(prereg["directory"]) / "manifest.json"),
        "test_feature_hash": key(test_manifest["artifacts"]),
        "test_evaluated_once": True, "test_threshold_search": False,
        "models": cfg["allowed_test_models"], "prediction_counts": dict(counts),
    }, files)
    return {**value, "directory": str(out)}


def report(cfg):
    final = finalize(cfg, cfg["runtime"]["device"])
    ablation = ablate(cfg, cfg["runtime"]["device"])
    parsing = compare_parsing(cfg)
    final_dir = Path(final["directory"])
    metrics = _read(final_dir / "metrics.json")
    uncertainty = _read(final_dir / "uncertainty.json")
    release = _read(final_dir / "release_manifest.json")
    parsing_results = _read(Path(parsing["directory"]) / "results.json")
    ablation_rows = _read(Path(ablation["directory"]) / "summary.json")
    docs = Path(cfg["root"]) / "docs"
    docs.mkdir(exist_ok=True)
    path = docs / "w4_model_selection_report.md"

    def fmt(value):
        return "N/A" if value is None else f"{value:.6f}"

    lines = ["# W4 统一评测与模型冻结报告", "",
             f"发布：`{release['release']}`；默认模型：`{release['default_model']}`；"
             f"研究对照：`{release['research_model']}`。模型选择在测试前冻结，测试结果未反向调参。", "",
             "## 一次性测试结果", "",
             "| 模型 | TP | FP | FN | TN | F1 | AP | ROC-AUC | FPR |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for model in cfg["allowed_test_models"]:
        value = metrics[model]
        lines.append(f"| {model} | {value['tp']} | {value['fp']} | {value['fn']} | "
                     f"{value['tn']} | {fmt(value['f1'])} | {fmt(value['average_precision'])} | "
                     f"{fmt(value['roc_auc'])} | {fmt(value['fpr'])} |")
    lstm_values = [metrics[f"lstm_seed_{seed}"] for seed in cfg["lstm"]["seeds"]]
    lstm_f1 = [value["f1"] for value in lstm_values]
    lstm_ap = [value["average_precision"] for value in lstm_values]
    lines += ["",
              f"LSTM 三 seed：F1 `{np.mean(lstm_f1):.6f} ± {np.std(lstm_f1, ddof=1):.6f}`，"
              f"AP `{np.mean(lstm_ap):.6f} ± {np.std(lstm_ap, ddof=1):.6f}`（样本标准差）。",
              "验证到测试出现明显时间分布差异。测试阈值保持冻结，未针对测试重新搜索。"
              "由于共享原始行可能被多个 block 引用，当前没有可靠的唯一行级误报事件分母，"
              "FP事件/万唯一行与FP事件/小时记为 N/A，不以会话行数替代。", "",
              "## 配对不确定性", "",
              f"以 sampling_group 为单位、seed {uncertainty['seed']} 的 "
              f"{uncertainty['valid_replicates']} 次 Poisson 配对 bootstrap：",
              f"- ΔF1（LSTM seed42 - LR）均值 {fmt(uncertainty['delta_f1']['mean'])}，"
              f"95%区间 {uncertainty['delta_f1']['ci95']}。",
              f"- ΔAP（LSTM seed42 - LR）均值 {fmt(uncertainty['delta_ap']['mean'])}，"
              f"95%区间 {uncertainty['delta_ap']['ci95']}。", "",
              "## 解析表示对照（validation）", "",
              "| 表示 | F1 | AP | 特征数 |", "|---|---:|---:|---:|"]
    for name, value in parsing_results.items():
        lines.append(f"| {name} | {fmt(value['metrics']['f1'])} | "
                     f"{fmt(value['metrics']['average_precision'])} | {value['feature_count']} |")
    lines += ["", "## LSTM 核心消融（validation）", "",
              "| 变体 | seed | F1 | AP | ΔF1 | ΔAP |", "|---|---:|---:|---:|---:|---:|"]
    for row in ablation_rows:
        lines.append(f"| {row['variant']} | {row['seed']} | {fmt(row['f1'])} | "
                     f"{fmt(row['average_precision'])} | {fmt(row['delta_f1_vs_full'])} | "
                     f"{fmt(row['delta_ap_vs_full'])} |")
    lines += ["", "## 边界", "",
              "HDFS 仅提供 block 级异常标签，不提供真实根因类别或可信故障开始时刻。"
              "训练/验证间已知有164种相同模板序列；结果不能解释为跨系统泛化，也不报告生产MTTD。", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return {"report": str(path), "release": release, "metrics": metrics}


def inspect(cfg, model_id, session_id):
    final = finalize(cfg, cfg["runtime"]["device"])
    if model_id not in cfg["allowed_test_models"]:
        raise ValueError("Model is not part of the frozen release")
    table = pq.read_table(Path(final["directory"]) / "predictions.parquet")
    selected = table.filter(pc.and_(pc.equal(table["model_id"], model_id),
                                    pc.equal(table["block_id"], session_id))).to_pylist()
    if not selected:
        raise ValueError("Session is not present in the frozen test result")
    features = pq.read_table(Path(cfg["artifact_dir"]) / "test_features" / "sessions.parquet")
    row = features.filter(pc.equal(features["block_id"], session_id)).to_pylist()[0]
    return {**selected[0], "template_ids": row["template_ids"],
            "gap_seconds": row["gap_seconds"], "unknown_count": row["unknown_count"]}


def run(cfg, device_name="auto"):
    return {"preregister": preregister(cfg), "parsing": compare_parsing(cfg),
            "ablation": ablate(cfg, device_name), "final": finalize(cfg, device_name),
            "report": report(cfg)}
