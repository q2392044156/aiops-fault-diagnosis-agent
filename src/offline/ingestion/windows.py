"""按时间与组件生成统一滑动窗口。"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from offline.ingestion.adapters import parse_lines


# _stamp 返回可用于分桶的 UTC 时间。
def _stamp(row):
    value = (row.get("timestamp_utc") or row.get("timestamp")
             or row.get("timestamp_local"))
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


# make_windows 按来源/组件/时间生成滑动窗口。
def make_windows(rows, source_type, duration_seconds=60, step_seconds=10,
                 max_rows=500, min_rows=1):
    duration_seconds = max(1, int(duration_seconds))
    step_seconds = max(1, int(step_seconds))
    max_rows = max(1, int(max_rows))
    groups = defaultdict(list)
    for row in rows:
        groups[(source_type, row.get("component") or "unknown")].append(row)
    windows = []
    for (source, component), group in sorted(groups.items()):
        parsed = [(_stamp(row), row) for row in group]
        parsed = [(stamp, row) for stamp, row in parsed if stamp is not None]
        if not parsed:
            continue
        parsed.sort(key=lambda item: item[0])
        earliest = int(parsed[0][0].timestamp())
        latest = int(parsed[-1][0].timestamp())
        first_start = (earliest // step_seconds) * step_seconds
        for start_epoch in range(first_start, latest + 1, step_seconds):
            end_epoch = start_epoch + duration_seconds
            chunk_all = [row for stamp, row in parsed
                         if start_epoch <= int(stamp.timestamp()) < end_epoch]
            if len(chunk_all) < int(min_rows):
                continue
            start = datetime.fromtimestamp(start_epoch, UTC)
            for part in range(0, len(chunk_all), max_rows):
                chunk = chunk_all[part:part + max_rows]
                raw = f"{source}|{component}|{start.isoformat()}|{part // max_rows}"
                window_id = "win_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
                windows.append({
                    "window_id": window_id, "source_type": source,
                    "component": component, "start": start.isoformat(),
                    "end": end_epoch, "line_count": len(chunk), "rows": chunk,
                })
    return windows


# load_case_windows 解析案例日志并生成滑动窗口。
def load_case_windows(case_dir, source_type=None, duration_seconds=60,
                      step_seconds=10, max_rows=500):
    case_dir = Path(case_dir)
    incident = json.loads((case_dir / "incident.json").read_text(encoding="utf-8"))
    logs = list((case_dir / "evidence/logs").glob("*.log"))
    if not logs:
        return []
    if source_type is None:
        source_type = "wsl" if "wsl_cases" in str(case_dir) else "docker_container"
    rows = parse_lines(source_type, logs[0].read_text(encoding="utf-8", errors="replace").splitlines(),
                       case_dir.name, incident["timestamps"]["fault_start"])
    start = datetime.fromisoformat(
        incident["timestamps"]["fault_start"].replace("Z", "+00:00"))
    cutoff = incident.get("diagnosis_snapshot", {}).get("cutoff_time")
    end = (datetime.fromisoformat(cutoff.replace("Z", "+00:00"))
           if cutoff else start + timedelta(minutes=5))
    lower = (start - timedelta(seconds=60)).timestamp()
    upper = (end + timedelta(seconds=60)).timestamp()
    rows = [row for row in rows
            if _stamp(row) and lower <= _stamp(row).timestamp() <= upper]
    return make_windows(rows, source_type, duration_seconds, step_seconds, max_rows)


# load_normal_windows 从正常日志目录生成滑动窗口。
def load_normal_windows(directory, source_type="docker_container",
                        duration_seconds=60, step_seconds=10, max_rows=500):
    windows = []
    for log in sorted(Path(directory).glob("*.log")):
        rows = parse_lines(source_type,
                           log.read_text(encoding="utf-8", errors="replace").splitlines(),
                           log.name, "2026-10-28T00:00:00+00:00")
        windows.extend(make_windows(rows, source_type, duration_seconds, step_seconds,
                                     max_rows))
    return windows
