import json
import os
import platform
import subprocess
import time
from collections import Counter
from pathlib import Path

import joblib
import numpy as np
import psutil
import pyarrow as pa
import pyarrow.parquet as pq
import sklearn
from sklearn.ensemble import IsolationForest
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression

from aiops_diag.data.common import digest, key, save, verified_manifest
from .metrics import classification_metrics, select_threshold


def _load_rows(cfg):
    artifact = Path(cfg["artifact_dir"])
    verified_manifest(artifact, "templates.json")
    sessions = pq.read_table(artifact / "sessions.parquet").to_pylist()
    labels = {r["block_id"]: int(r["label"])
              for r in pq.read_table(artifact / "labels.parquet").to_pylist()}
    protocol = {r["block_id"]: r
                for r in pq.read_table(Path(cfg["protocol_dir"]) / "assignments.parquet").to_pylist()}
    for row in sessions:
        row["label"] = labels[row["block_id"]]
        row["host_alias"] = protocol[row["block_id"]].get("host_alias")
    train = [r for r in sessions if r["split"] == "train"]
    validation = [r for r in sessions if r["split"] == "validation"]
    return train, validation


def _document(row):
    return " ".join(f"T{value}" for value in row["template_ids"])


def _rule_scores(rows, rare):
    error = np.asarray([r["error_count"] / max(1, r["line_count"]) for r in rows], dtype=np.float64)
    rare_scores = np.asarray([
        sum(value in rare for value in r["template_ids"]) / max(1, r["line_count"])
        for r in rows
    ], dtype=np.float64)
    return error, rare_scores


def _isolation_features(rows, top_templates):
    positions = {value: index for index, value in enumerate(top_templates)}
    matrix = np.zeros((len(rows), len(top_templates) + 4), dtype=np.float32)
    for row_index, row in enumerate(rows):
        for value, count in Counter(row["template_ids"]).items():
            column = positions.get(value)
            if column is not None:
                matrix[row_index, column] = count
        length = max(1, row["line_count"])
        base = len(top_templates)
        matrix[row_index, base] = np.log1p(row["line_count"])
        matrix[row_index, base + 1] = row["warn_count"] / length
        matrix[row_index, base + 2] = row["error_count"] / length
        matrix[row_index, base + 3] = np.log1p(max(0.0, row["duration_seconds"]))
    return matrix


def _apply_threshold(scores, threshold):
    if threshold is None:
        return np.zeros(len(scores), dtype=np.int8)
    return (np.asarray(scores) >= threshold).astype(np.int8)


def _aggregate(results, parameters):
    grouped = {}
    for row in results:
        identity = tuple(row[name] for name in parameters)
        grouped.setdefault(identity, []).append(row)
    summaries = []
    for identity, rows in grouped.items():
        summaries.append({
            **dict(zip(parameters, identity)),
            "mean_f1": float(np.mean([r["metrics"]["f1"] or 0.0 for r in rows])),
            "mean_average_precision": float(np.mean([
                r["metrics"]["average_precision"] or 0.0 for r in rows])),
            "all_thresholds_useful": all(r["metrics"]["useful"] for r in rows),
        })
    return summaries


def _git_commit(root):
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True,
                              capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _run_id(cfg, templates):
    return "w2_" + key([cfg["config_hash"], templates["artifacts"],
                         templates["protocol_hash"]])[:16]


def _verify_upstream(cfg, manifest, run_dir):
    protocol = verified_manifest(cfg["protocol_dir"], "manifest.json")
    templates = verified_manifest(cfg["artifact_dir"], "templates.json")
    if protocol["membership_hash"] != manifest["protocol_hash"]:
        raise ValueError("Frozen data protocol hash does not match the model")
    if key(templates["artifacts"]) != manifest["template_manifest_hash"]:
        raise ValueError("Drain3/feature manifest hash does not match the model")
    if manifest["config_hash"] != cfg["config_hash"]:
        raise ValueError("Model configuration hash does not match")
    if (run_dir / "registry.json").exists():
        verified_manifest(run_dir, "registry.json")
    return templates


def train(cfg):
    templates = verified_manifest(cfg["artifact_dir"], "templates.json")
    if templates["config_hash"] != cfg["config_hash"]:
        raise ValueError("Template artifacts exist for a different config")
    run_id = _run_id(cfg, templates)
    run_dir = Path(cfg["experiment_dir"]) / run_id
    if (run_dir / "training.json").exists():
        manifest = verified_manifest(run_dir, "training.json")
        _verify_upstream(cfg, manifest, run_dir)
        return {**manifest, "run_id": run_id, "run_dir": str(run_dir)}
    run_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    process = psutil.Process(os.getpid())
    train_rows, validation_rows = _load_rows(cfg)
    if any(r["split"] == "test" for r in train_rows + validation_rows):
        raise ValueError("sealed test data entered W2 modeling")
    y_train = np.asarray([r["label"] for r in train_rows], dtype=np.int8)
    y_validation = np.asarray([r["label"] for r in validation_rows], dtype=np.int8)
    train_documents = [_document(r) for r in train_rows]
    validation_documents = [_document(r) for r in validation_rows]

    vectorize_started = time.monotonic()
    vectorizer = TfidfVectorizer(tokenizer=str.split, token_pattern=None, lowercase=False,
                                 ngram_range=(1, 1), dtype=np.float32)
    x_train = vectorizer.fit_transform(train_documents)
    x_validation = vectorizer.transform(validation_documents)
    vocabulary_hash = key(sorted(vectorizer.vocabulary_.items()))
    vectorize_elapsed = time.monotonic() - vectorize_started

    max_fpr = cfg["threshold"]["max_fpr"]
    lr_started = time.monotonic()
    lr_results = []
    lr_scores = {}
    for c_value in cfg["logistic_regression"]["c_values"]:
        for weight_name in cfg["logistic_regression"]["class_weights"]:
            class_weight = None if weight_name == "none" else weight_name
            for seed in cfg["seeds"]:
                before = time.monotonic()
                model = LogisticRegression(
                    C=float(c_value), class_weight=class_weight,
                    solver=cfg["logistic_regression"]["solver"],
                    max_iter=cfg["logistic_regression"]["max_iter"], random_state=seed,
                )
                model.fit(x_train, y_train)
                scores = model.decision_function(x_validation)
                metrics, _ = select_threshold(y_validation, scores, max_fpr)
                name = f"c={c_value}|weight={weight_name}|seed={seed}"
                lr_scores[name] = scores
                lr_results.append({"c": float(c_value), "class_weight": weight_name,
                                   "seed": seed, "elapsed_seconds": time.monotonic() - before,
                                   "metrics": metrics})
                if time.monotonic() - started > cfg["limits"]["max_wall_seconds"]:
                    raise TimeoutError("W2 CPU wall-clock limit exceeded during LR grid")
    lr_summary = _aggregate(lr_results, ["c", "class_weight"])
    lr_selected = max(
        lr_summary,
        key=lambda r: (r["mean_f1"], r["mean_average_precision"], -r["c"],
                       r["class_weight"] == "none"),
    )
    selected_lr = LogisticRegression(
        C=lr_selected["c"],
        class_weight=None if lr_selected["class_weight"] == "none" else lr_selected["class_weight"],
        solver=cfg["logistic_regression"]["solver"],
        max_iter=cfg["logistic_regression"]["max_iter"], random_state=cfg["seed"],
    ).fit(x_train, y_train)
    selected_lr_scores = selected_lr.decision_function(x_validation)
    expected_lr_scores = lr_scores[
        f"c={lr_selected['c']}|weight={lr_selected['class_weight']}|seed={cfg['seed']}"]
    if not np.array_equal(selected_lr_scores, expected_lr_scores):
        raise ValueError("LR deterministic refit check failed")
    lr_metrics, lr_threshold_curve = select_threshold(y_validation, selected_lr_scores, max_fpr)
    lr_elapsed = time.monotonic() - lr_started

    template_frequency = Counter(value for row in train_rows for value in row["template_ids"])
    rare = {value for value, count in template_frequency.items()
            if count <= cfg["features"]["rare_template_max_count"]}
    error_scores, rare_scores = _rule_scores(validation_rows, rare)
    error_metrics, error_curve = select_threshold(y_validation, error_scores, max_fpr)
    rare_metrics, rare_curve = select_threshold(y_validation, rare_scores, max_fpr)

    isolation_features_started = time.monotonic()
    top_templates = [value for value, _ in template_frequency.most_common(
        cfg["features"]["isolation_top_templates"])]
    x_if_train = _isolation_features(train_rows, top_templates)
    x_if_validation = _isolation_features(validation_rows, top_templates)
    isolation_feature_elapsed = time.monotonic() - isolation_features_started
    normal_mask = y_train == 0
    if not np.any(normal_mask):
        raise ValueError("Isolation Forest requires normal training sessions")
    if_started = time.monotonic()
    if_results = []
    if_scores = {}
    for estimators in cfg["isolation_forest"]["estimators"]:
        for seed in cfg["seeds"]:
            before = time.monotonic()
            model = IsolationForest(
                n_estimators=estimators,
                max_samples=min(cfg["isolation_forest"]["max_samples"], int(np.sum(normal_mask))),
                contamination="auto", random_state=seed, n_jobs=-1,
            ).fit(x_if_train[normal_mask])
            scores = -model.decision_function(x_if_validation)
            metrics, _ = select_threshold(y_validation, scores, max_fpr)
            name = f"estimators={estimators}|seed={seed}"
            if_scores[name] = scores
            if_results.append({"estimators": estimators, "seed": seed,
                               "fit_samples": int(np.sum(normal_mask)),
                               "elapsed_seconds": time.monotonic() - before,
                               "metrics": metrics})
            if time.monotonic() - started > cfg["limits"]["max_wall_seconds"]:
                raise TimeoutError("W2 CPU wall-clock limit exceeded during IF grid")
    if_summary = _aggregate(if_results, ["estimators"])
    if_selected = max(if_summary, key=lambda r: (r["mean_f1"], r["mean_average_precision"],
                                                  -r["estimators"]))
    selected_if = IsolationForest(
        n_estimators=if_selected["estimators"],
        max_samples=min(cfg["isolation_forest"]["max_samples"], int(np.sum(normal_mask))),
        contamination="auto", random_state=cfg["seed"], n_jobs=-1,
    ).fit(x_if_train[normal_mask])
    selected_if_scores = -selected_if.decision_function(x_if_validation)
    expected_if_scores = if_scores[
        f"estimators={if_selected['estimators']}|seed={cfg['seed']}"]
    if not np.array_equal(selected_if_scores, expected_if_scores):
        raise ValueError("Isolation Forest deterministic refit check failed")
    if_metrics, if_threshold_curve = select_threshold(y_validation, selected_if_scores, max_fpr)
    if_elapsed = time.monotonic() - if_started

    all_normal = classification_metrics(y_validation, np.zeros(len(y_validation), dtype=np.int8))
    all_anomaly = classification_metrics(y_validation, np.ones(len(y_validation), dtype=np.int8))
    method_results = {
        "constraint": {"max_fpr": max_fpr},
        "references": {"all_normal": all_normal, "all_anomaly": all_anomaly},
        "error_rule": error_metrics, "rare_rule": rare_metrics,
        "logistic_regression": {"selected": lr_selected, "metrics": lr_metrics,
                                "grid_runs": lr_results, "grid_summary": lr_summary},
        "isolation_forest": {"selected": if_selected, "metrics": if_metrics,
                             "grid_runs": if_results, "grid_summary": if_summary,
                             "fit_normal_only": True},
    }
    save(run_dir / "results.json", method_results)
    save(run_dir / "threshold_curves.json", {
        "error_rule": error_curve, "rare_rule": rare_curve,
        "logistic_regression": lr_threshold_curve, "isolation_forest": if_threshold_curve,
    })
    save(run_dir / "feature_spec.json", {
        "tfidf": {"unigram_only": True, "fit_split": "train", "vocabulary_hash": vocabulary_hash,
                  "vocabulary_size": len(vectorizer.vocabulary_)},
        "rare_templates": sorted(rare), "isolation_templates": top_templates,
        "forbidden_features": ["label", "block_id", "ip", "pid", "path"],
    })
    save(run_dir / "resolved_config.json", {
        "config_hash": cfg["config_hash"], "seed": cfg["seed"], "seeds": cfg["seeds"],
        "protocol": cfg["protocol_name"], "test_accessed": False,
    })
    joblib.dump(vectorizer, run_dir / "tfidf.joblib", compress=3)
    joblib.dump(selected_lr, run_dir / "logistic_regression.joblib", compress=3)
    joblib.dump(selected_if, run_dir / "isolation_forest.joblib", compress=3)

    thresholds = {
        "error_rule": error_metrics["threshold"], "rare_rule": rare_metrics["threshold"],
        "logistic_regression": lr_metrics["threshold"], "isolation_forest": if_metrics["threshold"],
    }
    prediction_rows = []
    for index, row in enumerate(validation_rows):
        prediction_rows.append({
            "block_id": row["block_id"], "split": "validation", "label": int(y_validation[index]),
            "host_alias": row["host_alias"], "start_time": row["start_time"],
            "end_time": row["end_time"], "line_count": row["line_count"],
            "first_log_id": row["first_log_id"], "last_log_id": row["last_log_id"],
            "template_ids": row["template_ids"],
            "error_rule_score": float(error_scores[index]),
            "rare_rule_score": float(rare_scores[index]),
            "logistic_regression_score": float(selected_lr_scores[index]),
            "isolation_forest_score": float(selected_if_scores[index]),
            "error_rule_prediction": int(_apply_threshold(error_scores[index:index + 1], thresholds["error_rule"])[0]),
            "rare_rule_prediction": int(_apply_threshold(rare_scores[index:index + 1], thresholds["rare_rule"])[0]),
            "logistic_regression_prediction": int(_apply_threshold(selected_lr_scores[index:index + 1], thresholds["logistic_regression"])[0]),
            "isolation_forest_prediction": int(_apply_threshold(selected_if_scores[index:index + 1], thresholds["isolation_forest"])[0]),
        })
    pq.write_table(pa.Table.from_pylist(prediction_rows), run_dir / "predictions.parquet", compression="zstd")
    training_files = ["results.json", "threshold_curves.json", "feature_spec.json",
                      "resolved_config.json", "tfidf.joblib", "logistic_regression.joblib",
                      "isolation_forest.joblib", "predictions.parquet"]
    manifest = {
        "schema_version": 1, "run_id": run_id, "git_commit": _git_commit(cfg["root"]),
        "config_hash": cfg["config_hash"], "protocol_hash": templates["protocol_hash"],
        "template_manifest_hash": key(templates["artifacts"]),
        "train_sessions": len(train_rows), "validation_sessions": len(validation_rows),
        "train_anomalies": int(np.sum(y_train)), "validation_anomalies": int(np.sum(y_validation)),
        "vocabulary_hash": vocabulary_hash, "thresholds": thresholds,
        "elapsed_seconds": time.monotonic() - started,
        "rss_bytes": process.memory_info().rss,
        "timings": {"feature_vectorization_seconds": vectorize_elapsed,
                    "lr_training_selection_seconds": lr_elapsed,
                    "isolation_feature_seconds": isolation_feature_elapsed,
                    "isolation_training_selection_seconds": if_elapsed},
        "deterministic_refit_checks": {"logistic_regression": True, "isolation_forest": True},
        "environment": {"python": platform.python_version(), "scikit_learn": sklearn.__version__},
        "test_accessed": False,
        "artifacts": {name: digest(run_dir / name) for name in training_files},
    }
    save(run_dir / "training.json", manifest)
    return {**manifest, "run_dir": str(run_dir)}


def load_registered(cfg, filename):
    manifest = train(cfg)
    run_dir = Path(manifest["run_dir"]).resolve()
    target = (run_dir / filename).resolve()
    if target.parent != run_dir or filename not in manifest["artifacts"]:
        raise ValueError("Only project-generated, registered model artifacts may be loaded")
    verified_manifest(run_dir, "training.json")
    _verify_upstream(cfg, manifest, run_dir)
    return joblib.load(target)


def predictions(cfg, split="validation"):
    if split == "test":
        raise ValueError("W2 sealed the test split; test prediction is forbidden")
    if split not in {"dev", "validation"}:
        raise ValueError("split must be dev or validation")
    manifest = train(cfg)
    if split == "validation":
        return {"run_id": manifest["run_id"], "split": split,
                "predictions": str(Path(manifest["run_dir"]) / "predictions.parquet"),
                "count": manifest["validation_sessions"]}
    # Dev is accepted for diagnostics, but it is never used to report W2 validation results.
    train_rows, _ = _load_rows(cfg)
    count = sum(bool(r["in_ddev"]) for r in train_rows)
    return {"run_id": manifest["run_id"], "split": "dev", "count": count,
            "status": "available in training features; no validation metric generated"}
