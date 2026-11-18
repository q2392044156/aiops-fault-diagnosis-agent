"""加载并查询事件时间窗内的指标序列，供只读工具使用。"""

from __future__ import annotations

import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

# FIELDS 是指标文件必须包含的列。
FIELDS = ("timestamp", "host_alias", "component", "metric", "value")


# _parse_time 把 ISO 时间字符串解析为带时区的 datetime。
def _parse_time(value):
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# MetricsStore 读取 CSV/JSONL 指标文件，并按主机与时间窗聚合。
class MetricsStore:
    """一个极小的指标仓库：够让 query_metrics 返回真实序列，又不引入时序数据库。

    文件列固定为 timestamp,host_alias,component,metric,value；
    没有文件时 available 为 False，工具保持原有的 not_available 语义。
    """

    # __init__ 读取指标文件并记录无效行数量。
    def __init__(self, path):
        self.path = Path(path) if path else None
        self.rows = []
        self.invalid_rows = 0
        if self.path and self.path.is_file():
            self.rows = self._load()

    # _load 按扩展名解析 CSV 或 JSONL，跳过缺列与坏行。
    def _load(self):
        rows = []
        if self.path.suffix.lower() == ".jsonl":
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                    rows.append(self._row(item))
                except (ValueError, TypeError):
                    self.invalid_rows += 1
            return [row for row in rows if row]

        with self.path.open("r", encoding="utf-8-sig", newline="") as stream:
            for item in csv.DictReader(stream):
                if not set(FIELDS) <= set(item):
                    self.invalid_rows += 1
                    continue
                row = self._row(item)
                if row:
                    rows.append(row)
                else:
                    self.invalid_rows += 1
        return rows

    # _row 把一行原始数据转换为统一结构，无法解析时返回 None。
    @staticmethod
    def _row(item):
        stamp = _parse_time(item.get("timestamp"))
        try:
            value = float(item.get("value"))
        except (TypeError, ValueError):
            return None
        if stamp is None:
            return None
        return {
            "timestamp": stamp.isoformat(),
            "stamp": stamp,
            "host_alias": item.get("host_alias") or None,
            "component": item.get("component") or None,
            "metric": str(item.get("metric") or "unknown"),
            "value": value,
        }

    # available 表示是否存在可查询的指标文件。
    @property
    def available(self):
        return bool(self.rows)

    # window 返回指定主机与时间窗内的指标摘要，最多保留 60 个采样点。
    def window(self, host_alias, start, end, slack_seconds=300, limit=60):
        start_at = _parse_time(start)
        end_at = _parse_time(end)
        if start_at is None or end_at is None:
            return []
        lower = start_at - timedelta(seconds=slack_seconds)
        upper = end_at + timedelta(seconds=slack_seconds)
        groups = {}
        for row in self.rows:
            if host_alias and row["host_alias"] and row["host_alias"] != host_alias:
                continue
            if not lower <= row["stamp"] <= upper:
                continue
            groups.setdefault(row["metric"], []).append(row)
        series = []
        for metric, items in sorted(groups.items()):
            items.sort(key=lambda item: item["stamp"])
            values = [item["value"] for item in items]
            points = items
            if len(points) > limit:
                step = max(1, len(points) // limit)
                points = points[::step][-limit:]
            series.append({
                "metric": metric,
                "component": items[0]["component"],
                "count": len(values),
                "min": round(min(values), 6),
                "max": round(max(values), 6),
                "mean": round(sum(values) / len(values), 6),
                "p95": round(sorted(values)[max(0, int(len(values) * 0.95) - 1)], 6),
                "last": round(values[-1], 6),
                "points": [{"timestamp": item["timestamp"], "value": round(item["value"], 6)}
                           for item in points],
            })
        return series
