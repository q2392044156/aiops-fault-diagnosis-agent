import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from aiops_diag.data.common import digest, key, save, verified_manifest


FEATURE_SCHEMA = pa.schema([
    ("block_id", pa.string()), ("split", pa.string()),
    ("sampling_group", pa.string()), ("ddev_role", pa.string()),
    ("dmain_role", pa.string()), ("template_ids", pa.list_(pa.int32())),
    ("gap_seconds", pa.list_(pa.float32())), ("session_length", pa.int32()),
    ("duration_seconds", pa.float64()), ("warn_ratio", pa.float32()),
    ("error_ratio", pa.float32()), ("first_log_id", pa.string()),
    ("last_log_id", pa.string()),
])


def _fraction(group, namespace, seed):
    value = key([namespace, group, seed])[:16]
    return int(value, 16) / float(16 ** 16)


def role_for(group, namespace, seed, fit_fraction):
    return "fit" if _fraction(group, namespace, seed) < fit_fraction else "holdout"


def _upstream(cfg):
    protocol = verified_manifest(cfg["protocol_dir"], "manifest.json")
    templates = verified_manifest(cfg["w2_artifact_dir"], "templates.json")
    if not protocol.get("frozen"):
        raise ValueError("W2 protocol is not frozen")
    if templates["protocol_hash"] != protocol["membership_hash"]:
        raise ValueError("W2 template and protocol hashes do not match")
    return protocol, templates


def _scaler(rows, gaps, assignments, cfg):
    fit_blocks = {block for block, row in assignments.items()
                  if row.get("in_dmain") and
                  role_for(row["sampling_group"], "dmain", cfg["seed"],
                           cfg["split"]["dmain_fit_fraction"]) == "fit"}
    gap_values = []
    lengths = []
    durations = []
    for row in rows:
        block = row["block_id"]
        if block not in fit_blocks:
            continue
        gap_values.extend(math.log1p(value) for value in gaps[block])
        lengths.append(math.log1p(row["line_count"]))
        durations.append(math.log1p(max(0.0, row["duration_seconds"])))
    if not gap_values or not lengths:
        raise ValueError("No Dmain fit values available for scaling")
    clip = float(np.percentile(np.asarray(gap_values, dtype=np.float64),
                               cfg["features"]["gap_clip_percentile"]))
    clipped = np.minimum(np.asarray(gap_values, dtype=np.float64), clip)

    def stats(values):
        values = np.asarray(values, dtype=np.float64)
        deviation = float(values.std())
        return {"mean": float(values.mean()), "std": deviation if deviation > 0 else 1.0}

    return {
        "fit_role": "dmain_fit_only", "gap_transform": "clip(log1p(max(delta,0)))",
        "gap_clip_percentile": cfg["features"]["gap_clip_percentile"],
        "gap_clip_log1p": clip, "gap": stats(clipped),
        "session_length_log1p": stats(lengths),
        "duration_log1p": stats(durations),
    }


def prepare_sequences(cfg):
    protocol, templates = _upstream(cfg)
    out = Path(cfg["feature_dir"])
    if (out / "manifest.json").exists():
        manifest = verified_manifest(out, "manifest.json")
        if manifest["config_hash"] != cfg["config_hash"]:
            raise ValueError("Sequence features exist for a different config")
        return manifest

    assignments = {row["block_id"]: row for row in
                   pq.read_table(Path(cfg["protocol_dir"]) / "assignments.parquet").to_pylist()}
    session_rows = pq.read_table(Path(cfg["w2_artifact_dir"]) / "sessions.parquet").to_pylist()
    wanted = {row["block_id"] for row in session_rows}
    gaps = {block: [] for block in wanted}
    previous = {}
    negative_gaps = invalid_timestamps = matched_messages = 0
    columns = ["timestamp_local", "session_ids"]
    for batch in pq.ParquetFile(Path(cfg["w1_dir"]) / "logs.parquet").iter_batches(
            columns=columns, batch_size=100000):
        for row in batch.to_pylist():
            selected = [block for block in row["session_ids"] if block in wanted]
            if not selected:
                continue
            try:
                stamp = datetime.fromisoformat(row["timestamp_local"])
            except (TypeError, ValueError):
                invalid_timestamps += len(selected)
                continue
            for block in selected:
                prior = previous.get(block)
                delta = 0.0 if prior is None else (stamp - prior).total_seconds()
                if delta < 0:
                    negative_gaps += 1
                    delta = 0.0
                gaps[block].append(float(delta))
                previous[block] = stamp
                matched_messages += 1
    if invalid_timestamps:
        raise ValueError(f"Sequence timestamps invalid for {invalid_timestamps} linked rows")
    for row in session_rows:
        block = row["block_id"]
        if len(gaps[block]) != len(row["template_ids"]):
            raise ValueError(f"Template/time alignment failed for {block}")

    scaler = _scaler(session_rows, gaps, assignments, cfg)
    feature_rows = []
    role_counts = Counter()
    for row in sorted(session_rows, key=lambda value: value["block_id"]):
        block = row["block_id"]
        assignment = assignments[block]
        ddev_role = None
        if assignment.get("in_ddev"):
            ddev_role = role_for(assignment["sampling_group"], "ddev", cfg["seed"],
                                 cfg["split"]["ddev_fit_fraction"])
            role_counts[f"ddev_{ddev_role}"] += 1
        dmain_role = None
        if assignment.get("in_dmain"):
            dmain_role = role_for(assignment["sampling_group"], "dmain", cfg["seed"],
                                  cfg["split"]["dmain_fit_fraction"])
            role_counts[f"dmain_{dmain_role}"] += 1
        length = max(1, row["line_count"])
        feature_rows.append({
            "block_id": block, "split": row["split"],
            "sampling_group": assignment["sampling_group"],
            "ddev_role": ddev_role, "dmain_role": dmain_role,
            "template_ids": [int(value) + 1 for value in row["template_ids"]],
            "gap_seconds": gaps[block], "session_length": row["line_count"],
            "duration_seconds": row["duration_seconds"],
            "warn_ratio": row["warn_count"] / length,
            "error_ratio": row["error_count"] / length,
            "first_log_id": row["first_log_id"], "last_log_id": row["last_log_id"],
        })

    out.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(feature_rows, schema=FEATURE_SCHEMA),
                   out / "sequence_features.parquet", compression="zstd")
    save(out / "scaler.json", scaler)
    whitelist = {
        "model_inputs": cfg["features"]["whitelist"],
        "metadata_only": ["block_id", "split", "sampling_group", "first_log_id", "last_log_id"],
        "forbidden": ["label", "block_id", "ip", "pid", "path", "raw_numeric_parameter"],
        "status_code": "not used: HDFS has no reliable audited status-code field",
    }
    save(out / "feature_whitelist.json", whitelist)
    vocab = json.loads((Path(cfg["w2_artifact_dir"]) / "template_vocab.json").read_text(encoding="utf-8"))
    mapping = {"PAD": cfg["features"]["pad_id"], "T_UNK": cfg["features"]["unknown_id"],
               "source_to_model": {source: int(source) + 1 for source in vocab}}
    save(out / "sequence_vocabulary.json", mapping)
    files = ["sequence_features.parquet", "scaler.json", "feature_whitelist.json",
             "sequence_vocabulary.json"]
    manifest = {
        "schema_version": 1, "feature_version": cfg["feature_version"],
        "config_hash": cfg["config_hash"], "protocol_hash": protocol["membership_hash"],
        "template_artifact_hash": key(templates["artifacts"]),
        "sessions": len(feature_rows), "matched_messages": matched_messages,
        "negative_gaps_clamped": negative_gaps, "invalid_timestamps": invalid_timestamps,
        "role_counts": dict(role_counts), "label_columns_present": False,
        "max_source_template_id": max(int(value) for value in vocab),
        "model_vocabulary_size": max(int(value) for value in vocab) + 2,
        "feature_membership_hash": key([(r["block_id"], r["split"], r["ddev_role"],
                                          r["dmain_role"]) for r in feature_rows]),
        "artifacts": {name: digest(out / name) for name in files},
    }
    save(out / "manifest.json", manifest)
    return manifest
