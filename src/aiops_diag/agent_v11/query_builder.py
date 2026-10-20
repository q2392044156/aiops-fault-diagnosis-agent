"""Deterministic, allowlisted retrieval query construction for v1.1 RC2."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from aiops_diag.data.common import digest, key


VERSION = re.compile(r"^\d+\.\d+\.\d+$")


def load_config(path: str | Path) -> dict:
    path = Path(path).resolve()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1 or raw.get("builder_version") != "query_builder_v1":
        raise ValueError("Unsupported query builder configuration")
    if int(raw.get("max_plans", 0)) not in (1, 2, 3):
        raise ValueError("Query builder max_plans must be between 1 and 3")
    trusted = raw.get("trusted_components")
    if not isinstance(trusted, list) or not trusted or len(trusted) != len(set(trusted)):
        raise ValueError("Query builder requires unique trusted components")
    for name, item in raw.get("signals", {}).items():
        if not name or not item.get("patterns") or not item.get("query_terms"):
            raise ValueError("Query builder signals require patterns and query terms")
    value = json.loads(json.dumps(raw))
    value["config_path"] = str(path)
    value["config_sha256"] = digest(path)
    return value


class RetrievalQueryBuilder:
    """Create safe queries using only canonical components and signal phrases."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.trusted = set(cfg["trusted_components"])
        self.max_plans = int(cfg["max_plans"])
        self.signals = cfg["signals"]
        self.severity = {name.upper(): int(value)
                         for name, value in cfg["severity_order"].items()}

    @property
    def public(self):
        return {"builder_version": self.cfg["builder_version"],
                "config_sha256": self.cfg["config_sha256"],
                "max_plans": self.max_plans}

    def _signals(self, row: dict) -> list[str]:
        # Text is inspected only for allowlisted substrings. It is never copied
        # into a query, state, audit argument or report.
        text = " ".join(str(row.get(name) or "") for name in (
            "template_id", "redacted_message")).casefold()
        return [name for name, item in self.signals.items()
                if any(str(pattern).casefold() in text for pattern in item["patterns"])]

    def build(self, log_rows: list[dict], product_version: str | None = None) -> list[dict]:
        if product_version is not None and not VERSION.fullmatch(product_version):
            product_version = None
        grouped = defaultdict(list)
        for row in log_rows:
            component = row.get("component")
            if component in self.trusted:
                grouped[component].append(row)
        ranked = []
        for component, rows in grouped.items():
            counts = Counter(signal for row in rows for signal in self._signals(row))
            max_severity = max((self.severity.get(str(row.get("level") or "").upper(), 0)
                                for row in rows), default=0)
            ranked.append((component, counts, max_severity, len(rows)))
        ranked.sort(key=lambda item: (-item[2], -sum(item[1].values()),
                                      -item[3], item[0]))
        plans = []
        for component, counts, _severity, _row_count in ranked[:self.max_plans]:
            matched = sorted(counts, key=lambda name: (-counts[name], name))
            terms = [self.signals[name]["query_terms"] for name in matched]
            if not terms:
                terms = [self.cfg["component_defaults"][component]]
            query = " ".join(["HDFS", component, *terms, "只读排查证据"])
            reason = (f"component_and_{len(matched)}_allowlisted_signals"
                      if matched else "component_default")
            plans.append({
                "builder_version": self.cfg["builder_version"],
                "component": component,
                "product_version": product_version,
                "matched_signals": matched,
                "query": query,
                "reason": reason,
                "plan_hash": key([self.cfg["builder_version"], component,
                                  product_version, matched, query]),
            })
        return plans

