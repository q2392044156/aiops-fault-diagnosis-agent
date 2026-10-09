import csv
import hashlib
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from aiops_diag.data.common import digest, key, save, verified_manifest

IP = re.compile(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])")


def _labels(cfg):
    path = Path(cfg["data"]["raw_dir"]) / "anomaly_label.csv"
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {r["BlockId"]: r["Label"] for r in csv.DictReader(f)}


def _first_messages(w1, wanted_lines):
    result = {}
    for batch in pq.ParquetFile(w1 / "logs.parquet").iter_batches(
            columns=["raw_line_no", "message"], batch_size=100000):
        for row in batch.to_pylist():
            n = row["raw_line_no"]
            if n in wanted_lines:
                result[n] = row["message"] or ""
        if len(result) == len(wanted_lines):
            break
    return result


def _event_clusters(blocks, max_gap, max_span):
    """Cluster by host proxy with a gap rule and a hard span cap."""
    by_host = defaultdict(list)
    singles = []
    for block, info in blocks.items():
        if info["host_alias"] is None:
            singles.append([block])
        else:
            by_host[info["host_alias"]].append((datetime.fromisoformat(info["start"]), block))
    clusters = singles
    for values in by_host.values():
        values.sort()
        current, start, previous = [], None, None
        for stamp, block in values:
            if not current or (stamp - previous <= max_gap and stamp - start <= max_span):
                current.append(block)
            else:
                clusters.append(current)
                current = [block]
                start = stamp
            if start is None:
                start = stamp
            previous = stamp
        if current:
            clusters.append(current)
    return clusters


def _sample_groups(assignments, limit, dataset_hash, seed):
    groups = defaultdict(list)
    for row in assignments:
        if row["split"] == "train":
            groups[row["sampling_group"]].append(row["block_id"])
    ordered = sorted(groups, key=lambda value: key([dataset_hash, value, seed]))
    selected = set()
    count = 0
    for group in ordered:
        size = len(groups[group])
        if count + size <= limit:
            selected.update(groups[group])
            count += size
        if count >= limit:
            break
    return selected


def freeze(cfg):
    w1 = Path(cfg["w1_dir"])
    out = Path(cfg["protocol_dir"])
    if (out / "manifest.json").exists():
        existing = verified_manifest(out, "manifest.json")
        if existing["config_hash"] != cfg["config_hash"]:
            raise ValueError("Frozen protocol exists for a different config; use a new protocol_name")
        return existing
    verified_manifest(w1, "build.json")
    w1_split = verified_manifest(w1, "split.json")
    labels = _labels(cfg)
    base = pq.read_table(w1 / "splits.parquet").to_pylist()
    by_block = {r["block_id"]: dict(r) for r in base}

    db = sqlite3.connect(w1 / "index.sqlite")
    sessions = {r[0]: {"start": r[1], "end": r[2]} for r in db.execute("SELECT block,lo,hi FROM sessions")}
    abnormal = sorted(b for b, label in labels.items() if label == "Anomaly")
    # The host proxy is retained for every session so false-positive event rates can
    # be computed with the same privacy-preserving observation.  Only abnormal
    # sessions use it to form split-protection event clusters.
    first_line = dict(db.execute("SELECT block,MIN(n) FROM links GROUP BY block"))
    messages = _first_messages(w1, set(first_line.values()))
    dataset_hash = verified_manifest(w1, "build.json")["source_hash"]
    host_aliases = {}
    for block in by_block:
        msg = messages.get(first_line.get(block), "")
        found = IP.search(msg)
        alias = hashlib.sha256((dataset_hash + "|" + found.group(0)).encode()).hexdigest()[:16] if found else None
        host_aliases[block] = alias
    event_input = {block: {**sessions[block], "host_alias": host_aliases[block]}
                   for block in abnormal if block in sessions}
    db.close()

    max_gap = timedelta(seconds=cfg["event_proxy"]["max_gap_seconds"])
    max_span = timedelta(seconds=cfg["event_proxy"]["max_span_seconds"])
    clusters = _event_clusters(event_input, max_gap, max_span)
    event_id = {}
    for members in clusters:
        value = "event_" + key(sorted(members))[:20]
        for block in members:
            event_id[block] = value

    event_boundary_excluded = 0
    for members in clusters:
        active = {by_block[b]["split"] for b in members if by_block[b]["split"] != "excluded"}
        has_boundary_excluded = any(by_block[b]["split"] == "excluded" and
                                    by_block[b]["reason"] in {"boundary_excluded", "embargo"} for b in members)
        if len(active) > 1 or (active and has_boundary_excluded):
            for block in members:
                if by_block[block]["split"] != "excluded":
                    event_boundary_excluded += 1
                by_block[block]["split"] = "excluded"
                by_block[block]["reason"] = "event_proxy_boundary"

    assignments = []
    for block in sorted(by_block):
        row = by_block[block]
        proxy = event_id.get(block)
        sampling_group = proxy or row["group_id"]
        assignments.append({**row, "host_alias": host_aliases.get(block),
                            "event_proxy_id": proxy, "sampling_group": sampling_group})

    dmain = _sample_groups(assignments, cfg["sampling"]["dmain_max_sessions"], dataset_hash, cfg["seed"])
    ddev_all = _sample_groups(assignments, cfg["sampling"]["ddev_max_sessions"], dataset_hash, cfg["seed"])
    ddev = ddev_all & dmain
    for row in assignments:
        row["in_dmain"] = row["block_id"] in dmain
        row["in_ddev"] = row["block_id"] in ddev

    out.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(assignments)
    pq.write_table(table, out / "assignments.parquet", compression="zstd")
    counts = {split: dict(Counter(labels[r["block_id"]] for r in assignments if r["split"] == split))
              for split in ("train", "validation", "test", "excluded")}
    proxy_splits = defaultdict(set)
    group_splits = defaultdict(set)
    for row in assignments:
        if row["split"] != "excluded":
            group_splits[row["group_id"]].add(row["split"])
        if row["event_proxy_id"] and row["split"] != "excluded":
            proxy_splits[row["event_proxy_id"]].add(row["split"])
    manifest = {
        "schema_version": 1,
        "protocol": cfg["protocol_name"],
        "frozen": True,
        "config_hash": cfg["config_hash"],
        "source_hash": dataset_hash,
        "w1_split_hash": w1_split["membership_hash"],
        "event_proxy": {"definition": "earliest observed IPv4 alias + gap/span",
                        "max_gap_seconds": cfg["event_proxy"]["max_gap_seconds"],
                        "max_span_seconds": cfg["event_proxy"]["max_span_seconds"],
                        "clusters": len(clusters), "blocks_excluded": event_boundary_excluded,
                        "cross_split_clusters": sum(len(v) > 1 for v in proxy_splits.values())},
        "counts": counts,
        "split_counts": dict(Counter(r["split"] for r in assignments)),
        "dmain_sessions": len(dmain), "ddev_sessions": len(ddev),
        "leakage_audit": {
            "block_overlap": 0,
            "raw_line_group_cross_split": sum(len(v) > 1 for v in group_splits.values()),
            "event_proxy_cross_split": sum(len(v) > 1 for v in proxy_splits.values()),
        },
        "membership_hash": key(assignments),
        "artifacts": {"assignments.parquet": digest(out / "assignments.parquet")},
    }
    save(out / "manifest.json", manifest)
    return manifest
