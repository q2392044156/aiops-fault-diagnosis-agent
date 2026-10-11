import json
import platform
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import psutil
import pyarrow.parquet as pq

from aiops_diag.data.common import save

from .pipeline import _raw_rows
from .release import FrozenRelease


def _percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def _meta():
    return {
        "python": platform.python_version(), "platform": platform.platform(),
        "cpu": platform.processor(), "logical_cpus": psutil.cpu_count(),
        "memory_bytes": psutil.virtual_memory().total,
    }


def _sequences(cfg, limit=128):
    path = Path(cfg["model"]["artifact_dir"]) / "sessions.parquet"
    values = []
    for batch in pq.ParquetFile(path).iter_batches(columns=["template_ids"], batch_size=limit):
        values.extend(row["template_ids"] for row in batch.to_pylist())
        if len(values) >= limit:
            return values[:limit]
    return values


def e1(cfg):
    model = FrozenRelease(cfg)
    source = _sequences(cfg)
    if not source:
        raise ValueError("No session sequences are available for E1")
    results = []
    process = psutil.Process()
    for size in (1, 32, 128):
        batch = [source[index % len(source)] for index in range(size)]
        for _ in range(20):
            model.score(batch)
        elapsed = []
        started = time.perf_counter()
        for _ in range(100):
            tick = time.perf_counter()
            model.score(batch)
            elapsed.append((time.perf_counter() - tick) * 1000)
        total = time.perf_counter() - started
        results.append({
            "batch": size, "iterations": 100, "p50_ms": _percentile(elapsed, 0.50),
            "p95_ms": _percentile(elapsed, 0.95), "sessions_per_second": size * 100 / total,
            "rss_bytes": process.memory_info().rss,
        })
    return results


def e2(cfg):
    model = FrozenRelease(cfg)
    source = Path(cfg["root"]) / "data" / "raw" / "HDFS.log"
    if not source.is_file():
        return {"status": "NOT_RUN", "reason": "data/raw/HDFS.log is unavailable"}
    source_hash = "benchmark"
    results = []
    process = psutil.Process()
    for target in (10_000, 100_000, 1_000_000):
        total = quarantined = matched = 0
        started = time.perf_counter()
        for row in _raw_rows(source, source_hash, cfg["processing"]["max_line_bytes"]):
            total += 1
            valid = (row.get("parse_status") == "ok" and row.get("timestamp_local")
                     and row.get("session_ids"))
            if valid:
                matched += int(model.template(row) != 0)
            else:
                quarantined += 1
            if total >= target:
                break
        elapsed = time.perf_counter() - started
        results.append({
            "target_lines": target, "actual_lines": total, "seconds": elapsed,
            "lines_per_second": total / elapsed, "quarantined_lines": quarantined,
            "matched_lines": matched, "rss_bytes": process.memory_info().rss,
        })
    model.assert_unchanged()
    return results


def e3(cfg):
    base = cfg.get("ui", {}).get("api_url", "http://127.0.0.1:8000").rstrip("/")
    client = httpx.Client(timeout=10, trust_env=False)
    try:
        client.get(base + "/api/v1/health/ready", timeout=3).raise_for_status()
    except httpx.HTTPError as exc:
        return {"status": "NOT_RUN", "reason": f"API unavailable: {exc}"}
    results = []
    for concurrency in (1, 2, 4):
        def request(_):
            tick = time.perf_counter()
            response = client.get(base + "/api/v1/operations/summary", timeout=10)
            return (time.perf_counter() - tick) * 1000, response.status_code
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            rows = list(pool.map(request, range(100)))
        timings = [row[0] for row in rows]
        results.append({
            "concurrency": concurrency, "requests": 100,
            "p50_ms": _percentile(timings, 0.50), "p95_ms": _percentile(timings, 0.95),
            "error_count": sum(status >= 400 for _, status in rows),
        })
    return results


def e4(cfg):
    times = []
    process = psutil.Process()
    for _ in range(5):
        started = time.perf_counter()
        FrozenRelease(cfg)
        times.append(time.perf_counter() - started)
    return {
        "mode": "in_process_model_load",
        "runs_seconds": times, "mean_seconds": statistics.mean(times),
        "p50_seconds": _percentile(times, 0.50), "p95_seconds": _percentile(times, 0.95),
        "rss_bytes": process.memory_info().rss,
        "container_startup": "measured separately by deployment smoke test",
    }


def run(cfg, suite="all"):
    selected = ("e1", "e2", "e3", "e4") if suite == "all" else (suite,)
    functions = {"e1": e1, "e2": e2, "e3": e3, "e4": e4}
    result = {"schema_version": 1, "environment": _meta(), "suites": {}}
    for name in selected:
        result["suites"][name] = functions[name](cfg)
    target = Path(cfg["root"]) / "experiments" / "w6" / f"benchmark_{suite}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    save(target, result)
    return result
