import csv
import hashlib
import json
import random
import re
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from drain3.file_persistence import FilePersistence
from drain3.masking import MaskingInstruction
from drain3.template_miner import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig

from aiops_diag.data.common import digest, key, save, verified_manifest


SESSION_SCHEMA = pa.schema([
    ("block_id", pa.string()), ("split", pa.string()), ("in_ddev", pa.bool_()),
    ("template_ids", pa.list_(pa.int32())), ("line_count", pa.int32()),
    ("warn_count", pa.int32()), ("error_count", pa.int32()),
    ("start_time", pa.string()), ("end_time", pa.string()),
    ("duration_seconds", pa.float64()), ("first_log_id", pa.string()),
    ("last_log_id", pa.string()), ("unknown_count", pa.int32()),
])

BLOCK = re.compile(r"\bblk_-?\d+\b")
IP = re.compile(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?::\d+)?(?![0-9])")
PATH = re.compile(r"(?<![A-Za-z0-9])(?:/[A-Za-z0-9._-]+){2,}")
HEX = re.compile(r"\b0x[0-9A-Fa-f]+\b")
NUM = re.compile(r"(?<![A-Za-z0-9])[-+]?\d+(?:\.\d+)?(?![A-Za-z0-9])")


def content(row):
    message = row["message"] or ""
    # Apply the same deterministic redaction before both fit and match.
    message = BLOCK.sub("<:BLOCK:>", message)
    message = IP.sub("<:IP:>", message)
    message = PATH.sub("<:PATH:>", message)
    message = HEX.sub("<:HEX:>", message)
    message = NUM.sub("<:NUM:>", message)
    return f'{row["level"] or "UNKNOWN"} {row["component"] or "UNKNOWN"}: {message}'


def miner_config(cfg, similarity):
    c = TemplateMinerConfig()
    c.drain_sim_th = float(similarity)
    c.drain_depth = int(cfg["parser"]["depth"])
    c.drain_max_children = int(cfg["parser"]["max_children"])
    c.drain_max_clusters = None
    c.parametrize_numeric_tokens = False
    c.snapshot_interval_minutes = 10**9
    c.masking_instructions = [
        MaskingInstruction(BLOCK.pattern, "BLOCK"),
        MaskingInstruction(IP.pattern, "IP"),
        MaskingInstruction(PATH.pattern, "PATH"),
        MaskingInstruction(HEX.pattern, "HEX"),
        MaskingInstruction(NUM.pattern, "NUM"),
    ]
    return c


def _membership(cfg):
    rows = pq.read_table(Path(cfg["protocol_dir"]) / "assignments.parquet").to_pylist()
    dmain = {r["block_id"] for r in rows if r["split"] == "train" and r["in_dmain"]}
    ddev = {r["block_id"] for r in rows if r["split"] == "train" and r["in_ddev"]}
    validation = {r["block_id"] for r in rows if r["split"] == "validation"}
    return dmain, ddev, validation


def _selected(row, members):
    return [block for block in row["session_ids"] if block in members]


def _candidate_review(cfg, ddev):
    started = time.monotonic()
    w1 = Path(cfg["w1_dir"])
    samples = []
    miners = {str(value): TemplateMiner(None, miner_config(cfg, value))
              for value in cfg["parser"]["candidate_similarity"]}
    counts = {name: 0 for name in miners}
    reservoir = []
    rng = random.Random(cfg["seed"])
    seen = 0
    for batch in pq.ParquetFile(w1 / "logs.parquet").iter_batches(
            columns=["raw_line_no", "level", "component", "message", "session_ids"], batch_size=50000):
        for row in batch.to_pylist():
            if not _selected(row, ddev):
                continue
            text = content(row)
            for name, miner in miners.items():
                miner.add_log_message(text)
                counts[name] += 1
            seen += 1
            candidate = {"raw_line_no": row["raw_line_no"], "redacted_input": text,
                         "level": row["level"], "component": row["component"]}
            if len(reservoir) < 200:
                reservoir.append(candidate)
            else:
                position = rng.randrange(seen)
                if position < 200:
                    reservoir[position] = candidate
    for sample in sorted(reservoir, key=lambda r: r["raw_line_no"]):
        row = dict(sample)
        for name, miner in miners.items():
            cluster = miner.match(sample["redacted_input"], full_search_strategy="always")
            row[f"template_{name}"] = cluster.get_template() if cluster else None
        samples.append(row)
    critical_loss = {
        name: sum((sample[f"template_{name}"] or "").count("<*>") for sample in samples)
        for name in miners
    }
    selected = min(critical_loss, key=lambda name: (critical_loss[name], float(name)))
    return {
        "selected_similarity": float(selected),
        "selection_rule": "fewest generic wildcards in stratified review; tie -> lower similarity",
        "review_status": "AI-assisted; independent human review pending",
        "critical_content_loss": critical_loss,
        "elapsed_seconds": time.monotonic() - started,
        "messages_fitted": counts,
        "cluster_counts": {name: len(miner.drain.clusters) for name, miner in miners.items()},
        "samples": samples,
    }


def _empty_state(split, in_ddev):
    return {"split": split, "in_ddev": in_ddev, "template_ids": [], "line_count": 0,
            "warn_count": 0, "error_count": 0, "start": None, "end": None,
            "first_log_id": None, "last_log_id": None, "unknown_count": 0}


def _add(state, row, template_id, unknown=False):
    state["template_ids"].append(template_id)
    state["line_count"] += 1
    state["warn_count"] += row["level"] == "WARN"
    state["error_count"] += row["level"] == "ERROR"
    stamp = row["timestamp_local"]
    state["start"] = min(state["start"] or stamp, stamp)
    state["end"] = max(state["end"] or stamp, stamp)
    state["first_log_id"] = state["first_log_id"] or row["log_id"]
    state["last_log_id"] = row["log_id"]
    state["unknown_count"] += unknown


def _write_sessions(path, states):
    rows = []
    for block in sorted(states):
        state = states[block]
        duration = (datetime.fromisoformat(state["end"]) - datetime.fromisoformat(state["start"])).total_seconds()
        rows.append({"block_id": block, "split": state["split"], "in_ddev": state["in_ddev"],
                     "template_ids": state["template_ids"], "line_count": state["line_count"],
                     "warn_count": state["warn_count"], "error_count": state["error_count"],
                     "start_time": state["start"], "end_time": state["end"],
                     "duration_seconds": duration, "first_log_id": state["first_log_id"],
                     "last_log_id": state["last_log_id"], "unknown_count": state["unknown_count"]})
    pq.write_table(pa.Table.from_pylist(rows, schema=SESSION_SCHEMA), path, compression="zstd")


def build_templates(cfg):
    protocol = verified_manifest(cfg["protocol_dir"], "manifest.json")
    if protocol["config_hash"] != cfg["config_hash"]:
        raise ValueError("Frozen protocol configuration does not match")
    artifact = Path(cfg["artifact_dir"])
    manifest_path = artifact / "templates.json"
    if manifest_path.exists():
        existing = verified_manifest(artifact, "templates.json")
        if existing["config_hash"] != cfg["config_hash"]:
            raise ValueError("Template artifacts exist for a different config")
        return existing
    artifact.mkdir(parents=True, exist_ok=True)
    dmain, ddev, validation = _membership(cfg)
    review = _candidate_review(cfg, ddev)
    # Wall time is diagnostic, not part of the deterministic review artifact.
    save(artifact / "template_review.json", {k: v for k, v in review.items()
                                              if k != "elapsed_seconds"})

    snapshot = artifact / "drain3_state.bin"
    if snapshot.exists():
        raise ValueError("Unregistered Drain3 snapshot exists")
    selected_similarity = review["selected_similarity"]
    miner = TemplateMiner(FilePersistence(str(snapshot)), miner_config(cfg, selected_similarity))
    states = {block: _empty_state("train", block in ddev) for block in dmain}
    w1 = Path(cfg["w1_dir"])
    started = time.monotonic()
    train_started = time.monotonic()
    train_messages = 0
    columns = ["log_id", "raw_line_no", "timestamp_local", "level", "component", "message", "session_ids"]
    for batch in pq.ParquetFile(w1 / "logs.parquet").iter_batches(columns=columns, batch_size=50000):
        for row in batch.to_pylist():
            selected = _selected(row, dmain)
            if not selected:
                continue
            result = miner.add_log_message(content(row))
            template_id = int(result["cluster_id"])
            for block in selected:
                _add(states[block], row, template_id)
            train_messages += 1
    miner.save_state("training_complete")
    train_elapsed = time.monotonic() - train_started
    snapshot_hash_before = digest(snapshot)

    inference = TemplateMiner(FilePersistence(str(snapshot)), miner_config(cfg, selected_similarity))
    states.update({block: _empty_state("validation", False) for block in validation})
    validation_started = time.monotonic()
    validation_messages = unknown_messages = 0
    for batch in pq.ParquetFile(w1 / "logs.parquet").iter_batches(columns=columns, batch_size=50000):
        for row in batch.to_pylist():
            selected = _selected(row, validation)
            if not selected:
                continue
            cluster = inference.match(content(row), full_search_strategy="always")
            unknown = cluster is None
            template_id = 0 if unknown else int(cluster.cluster_id)
            for block in selected:
                _add(states[block], row, template_id, unknown)
            validation_messages += 1
            unknown_messages += unknown
    snapshot_hash_after = digest(snapshot)
    validation_elapsed = time.monotonic() - validation_started
    if snapshot_hash_before != snapshot_hash_after:
        raise ValueError("Frozen inference changed Drain3 snapshot")

    _write_sessions(artifact / "sessions.parquet", states)
    labels = {}
    with (Path(cfg["data"]["raw_dir"]) / "anomaly_label.csv").open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if row["BlockId"] in states:
                labels[row["BlockId"]] = row["Label"]
    label_rows = [{"block_id": block, "label": 1 if labels[block] == "Anomaly" else 0,
                   "split": states[block]["split"]} for block in sorted(states)]
    pq.write_table(pa.Table.from_pylist(label_rows), artifact / "labels.parquet", compression="zstd")
    vocab = {str(c.cluster_id): c.get_template() for c in sorted(miner.drain.clusters, key=lambda c: c.cluster_id)}
    vocab["0"] = cfg["parser"]["unknown_token"]
    save(artifact / "template_vocab.json", vocab)
    template_counts = Counter(t for state in states.values() if state["split"] == "train" for t in state["template_ids"])
    save(artifact / "template_counts.json", dict(sorted(template_counts.items())))
    train_sequences = {key(state["template_ids"]) for state in states.values() if state["split"] == "train"}
    validation_sequences = {key(state["template_ids"]) for state in states.values()
                            if state["split"] == "validation"}
    files = ["drain3_state.bin", "sessions.parquet", "labels.parquet", "template_vocab.json",
             "template_counts.json", "template_review.json"]
    details = {
        "schema_version": 1, "protocol_hash": protocol["membership_hash"],
        "config_hash": cfg["config_hash"], "selected_similarity": selected_similarity,
        "train_sessions": len(dmain), "validation_sessions": len(validation),
        "train_messages": train_messages, "validation_messages": validation_messages,
        "templates": len(vocab) - 1, "validation_unknown_messages": unknown_messages,
        "validation_unknown_rate": unknown_messages / validation_messages if validation_messages else None,
        "sequence_audit": {"exact_hash_overlap": len(train_sequences & validation_sequences),
                           "train_unique_sequences": len(train_sequences),
                           "validation_unique_sequences": len(validation_sequences)},
        "snapshot_unchanged_after_inference": True, "elapsed_seconds": time.monotonic() - started,
        "timings": {"candidate_comparison_seconds": review["elapsed_seconds"],
                    "parser_fit_seconds": train_elapsed,
                    "validation_match_seconds": validation_elapsed},
        "artifacts": {name: digest(artifact / name) for name in files},
    }
    save(manifest_path, details)
    return details
