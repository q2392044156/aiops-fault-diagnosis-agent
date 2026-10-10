import json
import os
import platform
import subprocess
import time
from functools import partial
from pathlib import Path

import numpy as np
import psutil
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import torch
from sklearn.metrics import average_precision_score
from torch import nn
from torch.utils.data import DataLoader

from aiops_diag.data.common import digest, key, save, verified_manifest
from .lstm_model import (LSTMClassifier, SequenceDataset, collate_sequences,
                         resolve_device, seed_everything)
from .metrics import pr_curve, select_threshold
from .sequences import prepare_sequences


def _git_commit(root):
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True,
                              capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _load_data(cfg):
    manifest = verified_manifest(cfg["feature_dir"], "manifest.json")
    if manifest["config_hash"] != cfg["config_hash"]:
        raise ValueError("Sequence feature configuration does not match")
    rows = pq.read_table(Path(cfg["feature_dir"]) / "sequence_features.parquet").to_pylist()
    labels = {row["block_id"]: int(row["label"]) for row in
              pq.read_table(Path(cfg["w2_artifact_dir"]) / "labels.parquet").to_pylist()}
    scaler = json.loads((Path(cfg["feature_dir"]) / "scaler.json").read_text(encoding="utf-8"))
    if set(labels) != {row["block_id"] for row in rows}:
        raise ValueError("Feature and label session membership differs")
    return manifest, rows, labels, scaler


def _make_loader(rows, labels, scaler, cfg, shuffle, seed, batch_size=None):
    dataset = SequenceDataset(rows, labels, scaler, cfg["features"]["max_length"])
    generator = torch.Generator().manual_seed(seed)
    return DataLoader(
        dataset, batch_size=batch_size or cfg["training"]["batch_size"],
        shuffle=shuffle, num_workers=cfg["training"]["num_workers"], generator=generator,
        collate_fn=partial(collate_sequences, max_length=cfg["features"]["max_length"]),
        pin_memory=torch.cuda.is_available(),
    )


def _move(batch, device):
    return {name: value.to(device, non_blocking=True) if torch.is_tensor(value) else value
            for name, value in batch.items()}


def _score(model, loader, device):
    model.eval()
    labels, scores, records = [], [], []
    with torch.inference_mode():
        for original in loader:
            batch = _move(original, device)
            logits = model(batch["template_ids"], batch["gaps"], batch["mask"],
                           batch["chunk_valid"], batch["session_features"])
            batch_scores = torch.sigmoid(logits).detach().cpu().numpy()
            labels.extend(original["labels"].numpy().astype(np.int8).tolist())
            scores.extend(batch_scores.astype(np.float64).tolist())
            records.extend({"block_id": block, "first_log_id": first, "last_log_id": last}
                           for block, first, last in zip(original["block_ids"],
                                                         original["first_log_ids"],
                                                         original["last_log_ids"]))
    return np.asarray(labels, dtype=np.int8), np.asarray(scores, dtype=np.float64), records


def training_weight(rows, labels, mode, cap):
    """Calculate pos_weight exclusively from the supplied training members."""
    positives = sum(labels[row["block_id"]] == 1 for row in rows)
    negatives = len(rows) - positives
    if not positives:
        raise ValueError("Training subset contains no positive sessions")
    ratio = negatives / positives
    if mode == "one":
        value = 1.0
    elif mode == "capped":
        value = min(ratio, cap)
    elif mode == "full":
        value = ratio
    else:
        raise ValueError(f"Unknown weight mode: {mode}")
    return value, {"source": "current training subset only", "positive": positives,
                   "negative": negatives, "ratio": ratio, "mode": mode, "value": value}


def _train_once(train_rows, stop_rows, labels, scaler, cfg, hidden_dim, weight_mode,
                seed, device, max_epochs=None, session_feature_count=4):
    seed_everything(seed)
    model = LSTMClassifier(
        vocabulary_size=verified_manifest(cfg["feature_dir"], "manifest.json")["model_vocabulary_size"],
        embedding_dim=cfg["model"]["embedding_dim"], hidden_dim=hidden_dim,
        dropout=cfg["model"]["dropout"], session_feature_count=session_feature_count,
    ).to(device)
    weight_value, weight_audit = training_weight(
        train_rows, labels, weight_mode, cfg["training"]["capped_pos_weight"])
    criterion = nn.BCEWithLogitsLoss(pos_weight=torch.tensor([weight_value], device=device))
    optimizer = torch.optim.Adam(model.parameters(), lr=cfg["training"]["learning_rate"])
    train_loader = _make_loader(train_rows, labels, scaler, cfg, True, seed)
    stop_loader = _make_loader(stop_rows, labels, scaler, cfg, False, seed)
    best_ap = -1.0
    best_epoch = 0
    best_state = None
    patience_left = cfg["training"]["patience"]
    history = []
    started = time.monotonic()
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)
    for epoch in range(1, (max_epochs or cfg["training"]["max_epochs"]) + 1):
        model.train()
        loss_sum = 0.0
        count = 0
        max_gradient_before_clip = 0.0
        for original in train_loader:
            batch = _move(original, device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(batch["template_ids"], batch["gaps"], batch["mask"],
                           batch["chunk_valid"], batch["session_features"])
            loss = criterion(logits, batch["labels"])
            if not torch.isfinite(loss):
                raise ValueError("Non-finite LSTM loss")
            loss.backward()
            grad_norm = torch.nn.utils.clip_grad_norm_(model.parameters(),
                                                       cfg["training"]["gradient_clip"])
            if not torch.isfinite(grad_norm):
                raise ValueError("Non-finite LSTM gradient")
            max_gradient_before_clip = max(max_gradient_before_clip, float(grad_norm))
            optimizer.step()
            loss_sum += float(loss.detach()) * len(original["labels"])
            count += len(original["labels"])
        stop_labels, stop_scores, _ = _score(model, stop_loader, device)
        stop_ap = float(average_precision_score(stop_labels, stop_scores))
        history.append({"epoch": epoch, "train_loss": loss_sum / count,
                        "early_stop_ap": stop_ap,
                        "max_gradient_before_clip": max_gradient_before_clip})
        if stop_ap > best_ap + 1e-12:
            best_ap = stop_ap
            best_epoch = epoch
            best_state = {name: value.detach().cpu().clone()
                          for name, value in model.state_dict().items()}
            patience_left = cfg["training"]["patience"]
        else:
            patience_left -= 1
            if patience_left <= 0:
                break
        if time.monotonic() - started > cfg["training"]["max_wall_seconds"]:
            raise TimeoutError("Single LSTM training run exceeded the wall-clock limit")
    if best_state is None:
        raise ValueError("LSTM training produced no checkpoint")
    model.load_state_dict(best_state)
    elapsed = time.monotonic() - started
    resource = {
        "elapsed_seconds": elapsed,
        "rss_bytes": psutil.Process(os.getpid()).memory_info().rss,
        "cuda_peak_bytes": torch.cuda.max_memory_allocated(device) if device.type == "cuda" else 0,
        "device": str(device),
    }
    return model, {"best_epoch": best_epoch, "best_early_stop_ap": best_ap,
                   "history": history, "weight": weight_audit, "resource": resource}


def _overfit_check(rows, labels, scaler, cfg, device):
    ordered = sorted(rows, key=lambda row: key(["overfit", row["sampling_group"],
                                                row["block_id"], cfg["seed"]]))
    selected = None
    for size in cfg["training"]["overfit_sizes"]:
        candidate = ordered[:min(size, len(ordered))]
        if {labels[row["block_id"]] for row in candidate} == {0, 1}:
            selected = candidate
            break
    if selected is None:
        raise ValueError("Could not construct a two-class overfit sample")
    seed_everything(cfg["seed"])
    model = LSTMClassifier(
        verified_manifest(cfg["feature_dir"], "manifest.json")["model_vocabulary_size"],
        cfg["model"]["embedding_dim"], min(cfg["model"]["hidden_candidates"]),
        cfg["model"]["dropout"],
    ).to(device)
    loader = _make_loader(selected, labels, scaler, cfg, True, cfg["seed"])
    evaluation_loader = _make_loader(selected, labels, scaler, cfg, False, cfg["seed"])
    positives = sum(labels[row["block_id"]] == 1 for row in selected)
    negatives = len(selected) - positives
    criterion = nn.BCEWithLogitsLoss(
        pos_weight=torch.tensor([negatives / positives], device=device))
    optimizer = torch.optim.Adam(model.parameters(), lr=cfg["training"]["learning_rate"])
    losses = []
    for _ in range(cfg["training"]["overfit_max_epochs"]):
        model.train()
        total = count = 0
        for original in loader:
            batch = _move(original, device)
            optimizer.zero_grad(set_to_none=True)
            logits = model(batch["template_ids"], batch["gaps"], batch["mask"],
                           batch["chunk_valid"], batch["session_features"])
            loss = criterion(logits, batch["labels"])
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), cfg["training"]["gradient_clip"])
            optimizer.step()
            total += float(loss.detach()) * len(original["labels"])
            count += len(original["labels"])
        losses.append(total / count)
    y, scores, _ = _score(model, evaluation_loader, device)
    metrics, _ = select_threshold(y, scores, cfg["threshold"]["max_fpr"])
    reduction = 1 - losses[-1] / losses[0]
    passed = reduction >= 0.9 and (metrics["f1"] or 0) >= 0.98 and \
        (metrics["recall"] or 0) > 0 and metrics["tn"] > 0
    return {"sessions": len(selected), "positive": positives, "negative": negatives,
            "pos_weight": negatives / positives,
            "initial_loss": losses[0], "final_loss": losses[-1],
            "loss_reduction": reduction, "metrics": metrics, "passed": passed}


def _group_subset(rows, limit, namespace, seed):
    groups = {}
    for row in rows:
        groups.setdefault(row["sampling_group"], []).append(row)
    selected = []
    for group in sorted(groups, key=lambda value: key([namespace, value, seed])):
        if len(selected) + len(groups[group]) <= limit:
            selected.extend(groups[group])
        if len(selected) >= limit:
            break
    return selected


def tune_lstm(cfg, device_name="auto"):
    prepare_sequences(cfg)
    feature_manifest, rows, labels, scaler = _load_data(cfg)
    out = Path(cfg["feature_dir"]) / "tuning"
    if (out / "manifest.json").exists():
        manifest = verified_manifest(out, "manifest.json")
        if manifest["config_hash"] != cfg["config_hash"]:
            raise ValueError("LSTM tuning exists for a different config")
        return manifest
    device = resolve_device(device_name)
    ddev_fit = [row for row in rows if row["ddev_role"] == "fit"]
    ddev_holdout = [row for row in rows if row["ddev_role"] == "holdout"]
    overfit = _overfit_check(ddev_fit, labels, scaler, cfg, device)
    if not overfit["passed"]:
        raise ValueError("Ddev small-sample overfit check failed")

    candidates = []
    for hidden_dim in cfg["model"]["hidden_candidates"]:
        for weight_mode in cfg["training"]["weight_modes"]:
            model, audit = _train_once(ddev_fit, ddev_holdout, labels, scaler, cfg,
                                       hidden_dim, weight_mode, cfg["seed"], device)
            loader = _make_loader(ddev_holdout, labels, scaler, cfg, False, cfg["seed"])
            y, scores, _ = _score(model, loader, device)
            metrics, curve = select_threshold(y, scores, cfg["threshold"]["max_fpr"])
            row = {"hidden_dim": hidden_dim, "weight_mode": weight_mode,
                   "early_stop": audit, "metrics": metrics}
            candidates.append(row)
            if device.type == "cuda":
                torch.cuda.empty_cache()
    selected = max(candidates, key=lambda row: (
        row["metrics"]["average_precision"] or 0.0,
        row["metrics"]["f1"] or 0.0,
        -row["hidden_dim"], -abs(row["early_stop"]["weight"]["value"] - 1.0),
    ))
    selection = {"hidden_dim": selected["hidden_dim"],
                 "weight_mode": selected["weight_mode"],
                 "selection_rule": "AP, constrained F1, smaller hidden, weight closer to one"}

    learning_curves = []
    for value in cfg["training"]["learning_curve_sizes"]:
        subset = ddev_fit if value == "all" else _group_subset(
            ddev_fit, int(value), "learning_curve", cfg["seed"])
        model, audit = _train_once(subset, ddev_holdout, labels, scaler, cfg,
                                   selection["hidden_dim"], selection["weight_mode"],
                                   cfg["seed"], device)
        loader = _make_loader(ddev_holdout, labels, scaler, cfg, False, cfg["seed"])
        y, scores, _ = _score(model, loader, device)
        metrics, _ = select_threshold(y, scores, cfg["threshold"]["max_fpr"])
        learning_curves.append({"requested_sessions": value, "actual_sessions": len(subset),
                                "metrics": metrics, "best_epoch": audit["best_epoch"],
                                "elapsed_seconds": audit["resource"]["elapsed_seconds"]})
        if device.type == "cuda":
            torch.cuda.empty_cache()

    out.mkdir(parents=True, exist_ok=True)
    save(out / "overfit.json", overfit)
    save(out / "candidates.json", candidates)
    save(out / "selection.json", selection)
    save(out / "learning_curves.json", learning_curves)
    files = ["overfit.json", "candidates.json", "selection.json", "learning_curves.json"]
    manifest = {
        "schema_version": 1, "config_hash": cfg["config_hash"],
        "feature_hash": key(feature_manifest["artifacts"]),
        "device": str(device), "ddev_fit_sessions": len(ddev_fit),
        "ddev_holdout_sessions": len(ddev_holdout), "selected": selection,
        "artifacts": {name: digest(out / name) for name in files},
    }
    save(out / "manifest.json", manifest)
    return manifest


def _w2_lr_result(cfg):
    root = Path(cfg["experiment_root"])
    candidates = sorted(root.glob("w2_*/results.json"))
    if not candidates:
        raise ValueError("Registered W2 LR result is required for W3 comparison")
    value = json.loads(candidates[-1].read_text(encoding="utf-8"))
    return value["logistic_regression"]["metrics"]


def _run_id(cfg, feature_manifest, tuning_manifest):
    return "w3_" + key([cfg["config_hash"], feature_manifest["artifacts"],
                         tuning_manifest["selected"]])[:16]


def _verify_run(run_dir):
    """Verify the self-registering run manifest and every registered artifact."""
    run_dir = Path(run_dir)
    verified_manifest(run_dir, "registry.json")
    return verified_manifest(run_dir, "training.json")


def _environment(device):
    value = {
        "python": platform.python_version(), "platform": platform.platform(),
        "cpu_logical_count": psutil.cpu_count(logical=True),
        "memory_bytes": psutil.virtual_memory().total,
        "torch": torch.__version__, "torch_cuda": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(), "selected_device": str(device),
    }
    if torch.cuda.is_available():
        properties = torch.cuda.get_device_properties(0)
        value.update({"gpu": properties.name, "gpu_memory_bytes": properties.total_memory,
                      "cudnn": torch.backends.cudnn.version()})
    try:
        value["nvidia_smi_driver"] = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            check=True, capture_output=True, text=True).stdout.strip().splitlines()[0]
    except (OSError, subprocess.CalledProcessError, IndexError):
        value["nvidia_smi_driver"] = None
    return value


def load_registered_model(cfg, run_id, seed, device_name="cpu"):
    """Load only a hash-registered state_dict produced by this project."""
    root = Path(cfg["experiment_root"]).resolve()
    run_dir = (root / run_id).resolve()
    if run_dir.parent != root:
        raise ValueError("Invalid run ID")
    manifest = _verify_run(run_dir)
    if manifest["config_hash"] != cfg["config_hash"]:
        raise ValueError("Model configuration hash does not match")
    feature_manifest = verified_manifest(cfg["feature_dir"], "manifest.json")
    if key(feature_manifest["artifacts"]) != manifest["feature_hash"]:
        raise ValueError("Model feature hash does not match")
    versions = json.loads((run_dir / "model_versions.json").read_text(encoding="utf-8"))
    checkpoint_name = versions["checkpoints"].get(str(seed))
    if checkpoint_name is None or checkpoint_name not in manifest["artifacts"]:
        raise ValueError("Seed checkpoint is not registered")
    checkpoint = (run_dir / checkpoint_name).resolve()
    if checkpoint.parent != run_dir:
        raise ValueError("Checkpoint path escapes the registered run")
    device = resolve_device(device_name)
    model = LSTMClassifier(feature_manifest["model_vocabulary_size"],
                           cfg["model"]["embedding_dim"],
                           versions["selected"]["hidden_dim"],
                           cfg["model"]["dropout"]).to(device)
    model.load_state_dict(torch.load(checkpoint, map_location=device, weights_only=True))
    model.eval()
    return model, device


def train_lstm(cfg, device_name="auto"):
    feature_manifest = prepare_sequences(cfg)
    tuning_manifest = tune_lstm(cfg, device_name)
    _, rows, labels, scaler = _load_data(cfg)
    run_id = _run_id(cfg, feature_manifest, tuning_manifest)
    run_dir = Path(cfg["experiment_root"]) / run_id
    if (run_dir / "training.json").exists():
        manifest = _verify_run(run_dir)
        if manifest["config_hash"] != cfg["config_hash"]:
            raise ValueError("Registered LSTM run belongs to a different configuration")
        return {**manifest, "run_dir": str(run_dir)}
    run_dir.mkdir(parents=True, exist_ok=True)
    device = resolve_device(device_name)
    dmain_fit = [row for row in rows if row["dmain_role"] == "fit"]
    dmain_stop = [row for row in rows if row["dmain_role"] == "holdout"]
    validation = [row for row in rows if row["split"] == "validation"]
    selected = tuning_manifest["selected"]
    prediction_rows = []
    histories = {}
    seed_results = []
    threshold_curves = {}
    pr_curves = {}
    checkpoint_names = []
    started = time.monotonic()
    for seed in cfg["seeds"]:
        model, audit = _train_once(
            dmain_fit, dmain_stop, labels, scaler, cfg, selected["hidden_dim"],
            selected["weight_mode"], seed, device)
        checkpoint_name = f"lstm_seed_{seed}.pt"
        torch.save(model.state_dict(), run_dir / checkpoint_name)
        checkpoint_names.append(checkpoint_name)
        loader = _make_loader(validation, labels, scaler, cfg, False, seed)
        y, scores, records = _score(model, loader, device)
        metrics, curve = select_threshold(y, scores, cfg["threshold"]["max_fpr"])
        predictions = np.zeros(len(scores), dtype=np.int8) if metrics["threshold"] is None \
            else (scores >= metrics["threshold"]).astype(np.int8)
        for index, record in enumerate(records):
            prediction_rows.append({**record, "split": "validation", "seed": seed,
                                    "label": int(y[index]), "anomaly_score": float(scores[index]),
                                    "prediction": int(predictions[index])})
        histories[str(seed)] = audit
        seed_results.append({"seed": seed, "metrics": metrics,
                             "best_epoch": audit["best_epoch"],
                             "weight": audit["weight"], "resource": audit["resource"]})
        threshold_curves[str(seed)] = curve
        pr_curves[str(seed)] = pr_curve(y, scores)
        if device.type == "cuda":
            torch.cuda.empty_cache()

    pq.write_table(pa.Table.from_pylist(prediction_rows), run_dir / "predictions.parquet",
                   compression="zstd")
    save(run_dir / "training_histories.json", histories)
    save(run_dir / "threshold_curves.json", threshold_curves)
    save(run_dir / "pr_curves.json", pr_curves)
    metrics_names = ["precision", "recall", "f1", "average_precision", "roc_auc", "fpr"]
    summary = {}
    for name in metrics_names:
        values = [row["metrics"][name] for row in seed_results if row["metrics"][name] is not None]
        summary[name] = {"mean": float(np.mean(values)) if values else None,
                         "std": float(np.std(values)) if values else None,
                         "values": values}
    results = {"seeds": seed_results, "summary": summary,
               "w2_logistic_regression": _w2_lr_result(cfg),
               "test_accessed": False,
               "sequence_overlap_warning": "164 exact template sequence hashes overlap train/validation"}
    save(run_dir / "results.json", results)

    failures = {}
    for seed in cfg["seeds"]:
        values = [row for row in prediction_rows if row["seed"] == seed]
        false_positive = sorted((row for row in values if row["label"] == 0 and row["prediction"] == 1),
                                key=lambda row: (-row["anomaly_score"], row["block_id"]))[:10]
        false_negative = sorted((row for row in values if row["label"] == 1 and row["prediction"] == 0),
                                key=lambda row: (row["anomaly_score"], row["block_id"]))[:10]
        failures[str(seed)] = {"highest_false_positives": false_positive,
                               "lowest_false_negatives": false_negative}
    save(run_dir / "failure_cases.json", failures)
    save(run_dir / "environment.json", _environment(device))

    version_list = {
        "model": "single-layer unidirectional supervised LSTM",
        "run_id": run_id, "seeds": cfg["seeds"], "selected": selected,
        "protocol_hash": feature_manifest["protocol_hash"],
        "template_artifact_hash": feature_manifest["template_artifact_hash"],
        "feature_hash": key(feature_manifest["artifacts"]),
        "config_hash": cfg["config_hash"], "cpu_fallback_checked": False,
        "checkpoints": {str(seed): f"lstm_seed_{seed}.pt" for seed in cfg["seeds"]},
        "test_accessed": False,
    }
    save(run_dir / "model_versions.json", version_list)
    registered = ["predictions.parquet", "training_histories.json", "threshold_curves.json",
                  "pr_curves.json", "results.json", "failure_cases.json", "environment.json",
                  "model_versions.json", *checkpoint_names]
    manifest = {
        "schema_version": 1, "run_id": run_id, "config_hash": cfg["config_hash"],
        "feature_hash": key(feature_manifest["artifacts"]),
        "tuning_hash": key(tuning_manifest["artifacts"]),
        "git_commit": _git_commit(cfg["root"]), "device": str(device),
        "torch": torch.__version__, "cuda": torch.version.cuda,
        "train_sessions": len(dmain_fit), "early_stop_sessions": len(dmain_stop),
        "validation_sessions": len(validation), "elapsed_seconds": time.monotonic() - started,
        "cpu_fallback_checked": False, "test_accessed": False,
        "artifacts": {name: digest(run_dir / name) for name in registered},
    }
    save(run_dir / "training.json", manifest)
    save(run_dir / "registry.json", {"schema_version": 1,
                                      "artifacts": {"training.json": digest(run_dir / "training.json")}})
    _verify_run(run_dir)

    # Load through the public hash-verifying path and prove CPU portability.
    cpu_model, cpu_device = load_registered_model(cfg, run_id, cfg["seed"], "cpu")
    cpu_loader = _make_loader(validation[:64], labels, scaler, cfg, False, cfg["seed"], batch_size=64)
    cpu_labels, cpu_scores, _ = _score(cpu_model, cpu_loader, cpu_device)
    if len(cpu_labels) != len(validation[:64]) or not np.all(np.isfinite(cpu_scores)):
        raise ValueError("CPU fallback inference check failed")
    version_list["cpu_fallback_checked"] = True
    save(run_dir / "model_versions.json", version_list)
    manifest["cpu_fallback_checked"] = True
    manifest["artifacts"]["model_versions.json"] = digest(run_dir / "model_versions.json")
    save(run_dir / "training.json", manifest)
    save(run_dir / "registry.json", {"schema_version": 1,
                                      "artifacts": {"training.json": digest(run_dir / "training.json")}})
    _verify_run(run_dir)
    _write_report(cfg, manifest, results)
    return {**manifest, "run_dir": str(run_dir)}


def _write_report(cfg, manifest, results):
    path = Path(cfg["root"]) / "docs" / "w3_experiment_report.md"
    summary = results["summary"]
    lr = results["w2_logistic_regression"]
    lines = [
        "# W3 LSTM 验证实验报告", "",
        f"运行：`{manifest['run_id']}`；设备：`{manifest['device']}`；测试集保持封存。", "",
        "| 指标 | LSTM 三seed均值 | 标准差 | W2 LR |", "|---|---:|---:|---:|",
    ]
    for name in ("f1", "average_precision", "roc_auc", "fpr"):
        def display(value):
            return "N/A" if value is None else f"{value:.6f}"
        lines.append(f"| {name} | {display(summary[name]['mean'])} | "
                     f"{display(summary[name]['std'])} | {display(lr[name])} |")
    lines += ["", "训练/验证间存在164种相同模板序列，因此结果仅作为v0.1序列模型验证对照，"
              "不代表零泄漏或跨系统泛化。正式模型晋级与测试集一次性评估留W4。", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def evaluate_lstm(cfg, split="validation", device_name="auto"):
    if split == "test":
        raise ValueError("W3 sealed the test split; test evaluation is forbidden")
    if split not in {"dev", "validation"}:
        raise ValueError("split must be dev or validation")
    if split == "dev":
        return tune_lstm(cfg, device_name)
    training = train_lstm(cfg, device_name)
    run_dir = Path(training["run_dir"])
    _verify_run(run_dir)
    return json.loads((run_dir / "results.json").read_text(encoding="utf-8"))


def predict_lstm(cfg, split="validation", device_name="auto"):
    if split == "test":
        raise ValueError("W3 sealed the test split; test prediction is forbidden")
    if split not in {"dev", "validation"}:
        raise ValueError("split must be dev or validation")
    if split == "dev":
        tuning = tune_lstm(cfg, device_name)
        return {"split": "dev", "sessions": tuning["ddev_holdout_sessions"],
                "status": "tuning results registered"}
    training = train_lstm(cfg, device_name)
    return {"split": "validation", "sessions": training["validation_sessions"],
            "predictions": str(Path(training["run_dir"]) / "predictions.parquet"),
            "run_id": training["run_id"]}


def inspect_lstm(cfg, run_id, seed, session_id):
    root = Path(cfg["experiment_root"]).resolve()
    run_dir = (root / run_id).resolve()
    if run_dir.parent != root:
        raise ValueError("Invalid run ID")
    manifest = _verify_run(run_dir)
    if seed not in cfg["seeds"]:
        raise ValueError("Seed is not registered")
    table = pq.read_table(run_dir / "predictions.parquet")
    selected = table.filter(pc.and_(pc.equal(table["block_id"], session_id),
                                    pc.equal(table["seed"], seed))).to_pylist()
    if not selected:
        raise ValueError("Validation session/seed not found")
    feature_table = pq.read_table(Path(cfg["feature_dir"]) / "sequence_features.parquet")
    features = feature_table.filter(pc.equal(feature_table["block_id"], session_id)).to_pylist()[0]
    return {"run_id": manifest["run_id"], **selected[0],
            "template_ids": features["template_ids"],
            "gap_seconds": features["gap_seconds"],
            "session_features": {name: features[name] for name in
                                 ("session_length", "duration_seconds", "warn_ratio", "error_ratio")}}
