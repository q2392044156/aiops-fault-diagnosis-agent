import csv
import hashlib
import platform
import random
import shutil
import sqlite3
from collections import Counter
from pathlib import Path

import psutil
import pyarrow.parquet as pq

from .common import digest, save, verified_manifest
from .parser import parse
from .pipeline import connect, location


def audit(c):
    source, h, folder = location(c)
    build = verified_manifest(folder, "build.json")
    verified_manifest(folder, "split.json")
    dev = verified_manifest(folder, "subset.json")
    assignments = pq.read_table(folder / "splits.parquet").to_pylist()
    labels, duplicates, conflicts, invalid = {}, [], [], []
    label_path = Path(c["raw_dir"]) / "anomaly_label.csv"
    with label_path.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            b, label = r["BlockId"], r["Label"]
            if label not in ("Normal", "Anomaly"):
                invalid.append(b)
            if b in labels:
                duplicates.append(b)
                if labels[b] != label:
                    conflicts.append(b)
            labels[b] = label
    db = connect(folder)
    db.execute("CREATE TEMP TABLE membership(block TEXT PRIMARY KEY,gid TEXT,split TEXT)")
    db.executemany("INSERT INTO membership VALUES (?,?,?)", [(r["block_id"], r["group_id"], r["split"]) for r in assignments])
    shared = db.execute("SELECT COUNT(*) FROM (SELECT n FROM links JOIN membership USING(block) WHERE split!='excluded' GROUP BY n HAVING COUNT(DISTINCT split)>1)").fetchone()[0]
    duplicate_lines = db.execute("SELECT COALESCE(SUM(c-1),0) FROM (SELECT COUNT(*) c FROM lines GROUP BY hash HAVING c>1)").fetchone()[0]
    duplicate_sequences = db.execute("SELECT COUNT(*) FROM (SELECT sequence_hash FROM sessions JOIN membership USING(block) WHERE split!='excluded' GROUP BY sequence_hash HAVING COUNT(DISTINCT split)>1)").fetchone()[0]
    known = {r["block_id"] for r in assignments}
    label_counts = {part: dict(Counter(labels.get(r["block_id"], "missing") for r in assignments if r["split"] == part)) for part in ("train", "validation", "test", "excluded")}
    total = build["counts"]["total"]
    sample = set(random.Random(c["seed"]).sample(range(1, total + 1), min(200, total)))
    for status in ("format_error", "time_error", "decode_error"):
        sample.update(n for n, in db.execute("SELECT n FROM lines WHERE status=? LIMIT 5", (status,)))
    sample.update(n for n, in db.execute("SELECT n FROM links GROUP BY n HAVING COUNT(*)>1 LIMIT 5"))
    sample.update(n for n, in db.execute("SELECT n FROM links WHERE block LIKE 'blk_-%' LIMIT 5"))
    checks = []
    with source.open("rb") as f:
        for n in sorted(sample):
            offset, length, expected, status = db.execute("SELECT offset,length,hash,status FROM lines WHERE n=?", (n,)).fetchone()
            f.seek(offset); raw = f.read(length)
            row = parse(raw, n, offset, h)
            linked = sorted(b for b, in db.execute("SELECT block FROM links WHERE n=?", (n,)))
            ok = hashlib.sha256(raw).hexdigest() == expected and row["parse_status"] == status and row["session_ids"] == linked
            checks.append({"raw_line_no": n, "hash_and_parse_verified": ok, "parse_status": status,
                           "session_ids": linked, "raw": raw.decode("utf-8", errors="replace").rstrip(),
                           "component": row["component"], "timestamp": row["timestamp_local"],
                           "review_method": "automated_roundtrip; manual review separate"})
    lengths = Counter(count for count, in db.execute("SELECT count FROM sessions"))
    time_range = db.execute("SELECT MIN(lo),MAX(hi) FROM sessions").fetchone()
    db.close()
    full_download = False
    if (Path(c["raw_dir"]) / "download.json").exists():
        verified_manifest(c["raw_dir"], "download.json")
        full_download = True
    safe = (not (shared or duplicates or conflicts or invalid or known - labels.keys())
            and dev["blocks"] > 0 and dev["lines"] > 0
            and all(r["hash_and_parse_verified"] for r in checks))
    report = {"schema_version": 1, "dataset": c["dataset"], "source_hash": h,
        "label_source_hash": digest(label_path), "full_download_verified": full_download,
        "data_checks_pass": safe, "counts": build["counts"], "time_range": time_range,
        "label_counts": dict(Counter(labels.values())), "split_label_counts": label_counts,
        "reference_label_counts_match": len(labels) == 575061 and Counter(labels.values())["Anomaly"] == 16838,
        "duplicate_labels": duplicates, "conflicting_labels": conflicts, "invalid_labels": invalid,
        "missing_labels": sorted(known - labels.keys()), "labels_without_logs": sorted(labels.keys() - known),
        "cross_split_shared_lines": shared, "raw_duplicate_lines": duplicate_lines,
        "cross_split_normalized_sequence_hashes": duplicate_sequences,
        "session_length_histogram": dict(sorted(lengths.items())), "automated_sample_count": len(checks),
        "manual_review_status": "pending", "dev": dev, "build_seconds": build["elapsed_seconds"],
        "peak_sampled_rss_bytes": build["peak_sampled_rss_bytes"],
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
            "cpu": platform.processor(), "logical_cpus": psutil.cpu_count(),
            "memory_bytes": psutil.virtual_memory().total, "free_disk_bytes": shutil.disk_usage(folder).free},
        "protocol_status": "provisional; event proxy and template audit pending W2"}
    save(folder / "sample_review.json", checks)
    save(folder / "audit.json", report)
    if not safe:
        raise ValueError(f"Audit checks failed; see {folder / 'audit.json'}")
    return report
