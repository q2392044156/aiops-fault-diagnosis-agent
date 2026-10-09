import hashlib
import json
import shutil
import sqlite3
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import psutil
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from .common import digest, key, save, verified_manifest
from .parser import normalized, parse

LOG_SCHEMA = pa.schema([(name, typ) for name, typ in [
    ("log_id", pa.string()), ("raw_line_no", pa.int64()), ("byte_offset", pa.int64()),
    ("byte_length", pa.int64()), ("raw_hash", pa.string()), ("timestamp_original", pa.string()),
    ("timestamp_local", pa.string()), ("timestamp_utc", pa.string()), ("timezone_assumption", pa.string()),
    ("pid", pa.string()), ("level", pa.string()), ("component", pa.string()), ("message", pa.string()),
    ("session_ids", pa.list_(pa.string())), ("parse_status", pa.string())]])
LINK_SCHEMA = pa.schema([("block_id", pa.string()), ("raw_line_no", pa.int64())])


def location(c):
    source = Path(c["raw_dir"]) / "HDFS.log"
    h = digest(source)
    version = key({"schema": 1, "source": h, "config": semantic_config(c)})[:20]
    return source, h, Path(c["output_dir"]) / version


def semantic_config(c):
    return {k: v for k, v in c.items() if k not in ("raw_dir", "output_dir", "min_free_gb")}


def connect(folder):
    db = sqlite3.connect(Path(folder) / "index.sqlite")
    db.execute("PRAGMA cache_size=-65536")
    return db


def finish(folder, name, details, files):
    save(folder / name, {"schema_version": 1, **details,
                        "artifacts": {f: digest(folder / f) for f in files}})


def build(c):
    source, h, folder = location(c)
    if (folder / "build.json").exists():
        verified_manifest(folder, "build.json")
        return folder
    folder.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(folder).free < c["min_free_gb"] * 1024 ** 3:
        raise ValueError("Insufficient disk space")
    # A failed build is preserved; explicit inspection is required before retry.
    if (folder / "index.sqlite").exists():
        raise ValueError(f"Incomplete build exists: {folder}")
    start = time.monotonic()
    db = connect(folder)
    db.executescript("""
      CREATE TABLE lines(n INTEGER PRIMARY KEY, offset INTEGER, length INTEGER, hash TEXT, status TEXT);
      CREATE TABLE links(block TEXT, n INTEGER);
      CREATE TABLE sessions(block TEXT PRIMARY KEY, lo TEXT, hi TEXT, bad INTEGER, count INTEGER, sequence_hash TEXT);
    """)
    states, hashes, counts = {}, {}, Counter()
    offset, previous, peak = 0, None, 0
    min_time, max_time = None, None
    rows, links, locators = [], [], []

    def flush(lw, aw):
        nonlocal peak
        lw.write_table(pa.Table.from_pylist(rows, schema=LOG_SCHEMA))
        aw.write_table(pa.Table.from_pylist(links, schema=LINK_SCHEMA))
        db.executemany("INSERT INTO lines VALUES (?,?,?,?,?)", locators)
        db.executemany("INSERT INTO links VALUES (?,?)", [(r["block_id"], r["raw_line_no"]) for r in links])
        db.commit()
        peak = max(peak, psutil.Process().memory_info().rss)
        rows.clear(); links.clear(); locators.clear()

    try:
        with pq.ParquetWriter(folder / "logs.parquet", LOG_SCHEMA, compression="zstd") as lw, \
             pq.ParquetWriter(folder / "links.parquet", LINK_SCHEMA, compression="zstd") as aw, source.open("rb") as stream:
            for n, raw in enumerate(stream, 1):
                row = parse(raw, n, offset, h)
                offset += len(raw)
                counts["total"] += 1
                counts[row["parse_status"]] += 1
                counts["no_block"] += not row["session_ids"]
                counts["multi_block"] += len(row["session_ids"]) > 1
                for field in ("timestamp_local", "pid", "level", "component", "message"):
                    counts["missing_" + field] += row[field] is None
                ts = row["timestamp_local"]
                if ts:
                    min_time = min(min_time or ts, ts)
                    max_time = max(max_time or ts, ts)
                    counts["time_reversals"] += previous is not None and ts < previous
                    previous = ts
                message = normalized(row).encode()
                for block in row["session_ids"]:
                    state = states.setdefault(block, [None, None, 0, 0])
                    if ts:
                        state[0] = min(state[0] or ts, ts)
                        state[1] = max(state[1] or ts, ts)
                    state[2] |= row["parse_status"] != "ok"
                    state[3] += 1
                    hasher = hashes.setdefault(block, hashlib.sha256())
                    hasher.update(len(message).to_bytes(4, "big") + message)
                    links.append({"block_id": block, "raw_line_no": n})
                rows.append(row)
                locators.append((n, row["byte_offset"], len(raw), row["raw_hash"], row["parse_status"]))
                if len(rows) >= c["batch_size"]:
                    flush(lw, aw)
                    if n % 1000000 == 0:
                        print(f"Indexed {n:,} lines", flush=True)
            if rows:
                flush(lw, aw)
        db.executemany("INSERT INTO sessions VALUES (?,?,?,?,?,?)",
                       ((b, *s, hashes[b].hexdigest()) for b, s in states.items()))
        db.executescript("CREATE INDEX links_block ON links(block); CREATE INDEX links_n ON links(n); CREATE INDEX lines_hash ON lines(hash);")
        db.commit()
    finally:
        db.close()
    finish(folder, "build.json", {"source_hash": h, "source": str(source), "config_hash": key(semantic_config(c)),
           "counts": dict(counts), "time_range": [min_time, max_time], "elapsed_seconds": time.monotonic() - start,
           "peak_sampled_rss_bytes": peak}, ["index.sqlite", "logs.parquet", "links.parquet"])
    return folder


def split(c):
    _, _, folder = location(c)
    build_info = verified_manifest(folder, "build.json")
    target = folder / "split.json"
    if target.exists():
        return verified_manifest(folder, "split.json")
    db = connect(folder)
    sessions = {r[0]: r[1:] for r in db.execute("SELECT block,lo,hi,bad,count FROM sessions")}
    if not sessions:
        raise ValueError("No block sessions")
    parent = {b: b for b in sessions}

    def find(b):
        while parent[b] != b:
            parent[b] = parent[parent[b]]
            b = parent[b]
        return b

    prev_n, first = None, None
    for b, n in db.execute("SELECT block,n FROM links ORDER BY n"):
        if n == prev_n:
            a, z = sorted((find(first), find(b)))
            parent[z] = a
        else:
            first, prev_n = b, n
    if not all(build_info["time_range"]):
        raise ValueError("No valid timestamps")
    lo, hi = map(datetime.fromisoformat, build_info["time_range"])
    boundaries = [lo + (hi - lo) * f for f in (0.6, 0.8)]
    embargo = timedelta(seconds=c["embargo_seconds"])
    groups = {}
    for b, s in sessions.items():
        groups.setdefault(find(b), []).append(b)
    assignments, group_rows = [], []
    for g, members in sorted(groups.items()):
        entries = [sessions[b] for b in members]
        bad = any(s[2] or not s[0] for s in entries)
        a = min((s[0] for s in entries if s[0]), default=None)
        z = max((s[1] for s in entries if s[1]), default=None)
        reason, part = "", "excluded"
        if bad:
            reason = "invalid_session"
        else:
            a, z = datetime.fromisoformat(a), datetime.fromisoformat(z)
            if any(a < b <= z for b in boundaries):
                reason = "boundary_excluded"
            elif any(a < b + embargo and z >= b - embargo for b in boundaries):
                reason = "embargo"
            else:
                part = "train" if z < boundaries[0] else "validation" if a < boundaries[1] else "test"
        group_rows.append({"group_id": g, "split": part, "reason": reason, "block_count": len(members)})
        assignments.extend({"block_id": b, "group_id": g, "split": part, "reason": reason} for b in sorted(members))
    db.close()
    pq.write_table(pa.Table.from_pylist(assignments), folder / "splits.parquet")
    save(folder / "groups.json", group_rows)
    finish(folder, "split.json", {"protocol": "provisional_time_shared_line_v1", "config_hash": key(semantic_config(c)),
           "boundaries": [b.isoformat() for b in boundaries], "embargo_seconds": c["embargo_seconds"],
           "counts": dict(Counter(r["split"] for r in assignments)), "membership_hash": key(assignments)},
           ["splits.parquet", "groups.json"])


def subset(c):
    _, h, folder = location(c)
    verified_manifest(folder, "build.json")
    verified_manifest(folder, "split.json")
    groups = json.loads((folder / "groups.json").read_text())
    assignments = pq.read_table(folder / "splits.parquet").to_pylist()
    db = connect(folder)
    db.execute("CREATE TEMP TABLE membership(block TEXT PRIMARY KEY, gid TEXT)")
    db.executemany("INSERT INTO membership VALUES (?,?)", [(r["block_id"], r["group_id"]) for r in assignments])
    sizes = dict(db.execute("SELECT gid,COUNT(DISTINCT n) FROM links JOIN membership USING(block) GROUP BY gid"))
    groups = sorted((g for g in groups if g["split"] == "train"), key=lambda g: key([c["dataset"], h, g["group_id"], c["seed"]]))
    chosen, blocks, lines = set(), 0, 0
    for g in groups:
        if blocks >= c["target_blocks"]:
            break
        count = sizes[g["group_id"]]
        if lines + count <= c["max_lines"]:
            chosen.add(g["group_id"])
            blocks += g["block_count"]
            lines += count
    members = [r for r in assignments if r["group_id"] in chosen]
    selected_blocks = {r["block_id"] for r in members}
    numbers = set()
    for b in selected_blocks:
        numbers.update(n for n, in db.execute("SELECT n FROM links WHERE block=?", (b,)))
    db.close()
    selected_numbers = pa.array(sorted(numbers), type=pa.int64())
    staged = folder / "dev_logs.parquet.tmp"
    with pq.ParquetWriter(staged, LOG_SCHEMA, compression="zstd") as writer:
        for batch in pq.ParquetFile(folder / "logs.parquet").iter_batches(batch_size=c["batch_size"]):
            selected = batch.filter(pc.is_in(batch.column("raw_line_no"), value_set=selected_numbers))
            if selected.num_rows:
                writer.write_table(pa.Table.from_batches([selected], schema=LOG_SCHEMA))
    staged.replace(folder / "dev_logs.parquet")
    save(folder / "dev_members.json", members)
    finish(folder, "subset.json", {"seed": c["seed"], "blocks": blocks, "lines": lines,
           "membership_hash": key(members), "line_membership_hash": key(sorted(numbers))},
           ["dev_members.json", "dev_logs.parquet"])


def trace(c, log_id):
    source, h, folder = location(c)
    prefix, n = log_id.rsplit(":", 1)
    if prefix != h:
        raise ValueError("Source hash does not match log ID")
    with connect(folder) as db:
        record = db.execute("SELECT offset,length,hash FROM lines WHERE n=?", (int(n),)).fetchone()
    if record is None:
        raise ValueError("Log ID not found")
    with source.open("rb") as f:
        f.seek(record[0]); raw = f.read(record[1])
    if hashlib.sha256(raw).hexdigest() != record[2]:
        raise ValueError("Raw line hash mismatch")
    return {"log_id": log_id, "raw": raw.decode("utf-8", errors="replace"), "verified": True}
