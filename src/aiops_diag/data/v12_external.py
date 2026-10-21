"""Prepare LogHub Hadoop and HDFS v3 TraceBench for the v1.2 public-data track.

The adapters deliberately keep injected-fault labels separate from production
root-cause labels.  Raw logs and traces are referenced by hashes; they are not
copied into the normalized JSONL records.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from aiops_diag.data.v12_contracts import (DiagnosticSnapshotV12,
                                            EvaluationLabelV12,
                                            ExternalEventV12)


SCHEMA_VERSION = 1
ADAPTER_VERSION = "v12_open_data_v1"
DEFAULT_SEED = 20261021

HADOOP_TIMESTAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})")
HADOOP_LOG_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}\s+"
    r"(?P<level>TRACE|DEBUG|INFO|WARN|ERROR|FATAL)\s+"
    r"(?:\[[^]]*\]\s+)?(?P<logger>[\w.$-]+):"
)
APPLICATION_RE = re.compile(r"^application_(\d+)_(\d+)$")
BLOCK_RE = re.compile(r"\bblk_-?\d+\b", re.IGNORECASE)
IP_RE = re.compile(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?::\d+)?(?![0-9])")
PATH_RE = re.compile(r"(?<![A-Za-z0-9])(?:[/\\][A-Za-z0-9._-]+){2,}")
SECRET_RE = re.compile(
    r"(?i)(?:api[_-]?key|token|authorization|cookie|password)\s*[:=]\s*\S+"
)
UNTRUSTED_RE = re.compile(
    r"(?i)ignore\s+(?:all\s+)?previous|system\s+prompt|https?://|file://|"
    r"\b(?:curl|wget|powershell|cmd\.exe|sudo|kubectl|systemctl)\b|\brm\s+-"
)
NUMBER_RE = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?")

SAFE_SIGNAL_PATTERNS = {
    "safe_mode": ("safe mode", "safemode"),
    "heartbeat_missing": ("heartbeat", "heart beat", "lost datanode", "dead datanode"),
    "block_report_delayed": ("block report", "blockreport"),
    "failed_volume": ("failed volume", "volume failure"),
    "under_replicated": ("under replicated", "under-replicated"),
    "journal_quorum": ("journalnode", "journal node", "quorum"),
    "namenode_unavailable": ("namenode unavailable", "connection refused", "rpc unavailable"),
    "standby_lag": ("standby lag", "standby namenode"),
    "write_pipeline": ("datastreamer", "write pipeline", "pipeline"),
    "lease_recovery": ("lease recovery", "recover lease"),
}

TRACEBENCH_INJECTION_LABELS = {
    "AN_Data_corruptBlk": "data_corrupt_block",
    "AN_Data_corruptMeta": "data_corrupt_metadata",
    "AN_Data_cutBlk": "data_truncate_block",
    "AN_Data_cutMeta": "data_truncate_metadata",
    "AN_Data_lossBlk": "data_loss_block",
    "AN_Data_lossMeta": "data_loss_metadata",
    "AN_Net_disconnectDN": "network_disconnect_datanode",
    "AN_Net_slowDN": "network_slow_datanode",
    "AN_Net_slowHDFS": "network_slow_hdfs",
    "AN_Proc_killDN": "process_kill_datanode",
    "AN_Proc_suspendDN": "process_suspend_datanode",
    "AN_Sys_deadDN": "system_dead_datanode",
    "AN_Sys_panicDN": "system_panic_datanode",
    "AN_Sys_readOnlyDN": "system_read_only_datanode",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def md5_file(path: Path) -> str:
    digest = hashlib.md5()  # noqa: S324 - upstream dataset integrity metadata uses MD5.
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staged = path.with_suffix(path.suffix + ".tmp")
    staged.write_text(text, encoding="utf-8", newline="\n")
    staged.replace(path)


def _write_json(path: Path, value: Any) -> None:
    _atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    content = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    _atomic_text(path, content)


def _event_id(dataset: str, source_unit_id: str) -> str:
    suffix = hashlib.sha256(f"{dataset}\0{source_unit_id}".encode()).hexdigest()[:20]
    return f"evt_ext_{dataset}_{suffix}"


def _evidence_ref(path: Path, source_root: Path) -> dict[str, Any]:
    content_sha256 = sha256_file(path)
    return {
        "ref_id": f"sha256:{content_sha256}",
        "relative_path": path.relative_to(source_root).as_posix(),
        "content_sha256": content_sha256,
        "bytes": path.stat().st_size,
        "redaction_status": "not_exported",
        "observed_at": None,
    }


def _safe_template(message: str) -> str:
    if UNTRUSTED_RE.search(message):
        return "<UNTRUSTED_TEXT_REDACTED>"
    message = SECRET_RE.sub("<SECRET>", message)
    message = BLOCK_RE.sub("<BLOCK>", message)
    message = IP_RE.sub("<IP>", message)
    message = PATH_RE.sub("<PATH>", message)
    message = NUMBER_RE.sub("<NUM>", message)
    return " ".join(message.split())[:500]


def _signals(values: Iterable[str]) -> list[str]:
    joined = " ".join(values).casefold()
    return sorted(name for name, patterns in SAFE_SIGNAL_PATTERNS.items()
                  if any(pattern in joined for pattern in patterns))


def _component(logger: str) -> str:
    lowered = logger.lower()
    if "datanode" in lowered:
        return "DataNode"
    if "namenode" in lowered:
        return "NameNode"
    if "resourcemanager" in lowered:
        return "ResourceManager"
    if "nodemanager" in lowered:
        return "NodeManager"
    if "mapreduce" in lowered or "mapred" in lowered:
        return "MapReduce"
    if "yarn" in lowered:
        return "YARN"
    if "hdfs" in lowered or ".dfs." in lowered:
        return "HDFS Client"
    return "Other"


def parse_hadoop_labels(path: Path) -> dict[str, dict[str, str]]:
    """Parse the public README-like label file into application-level labels."""
    workload: str | None = None
    fault: str | None = None
    labels: dict[str, dict[str, str]] = {}
    fault_names = {
        "Normal": "normal",
        "Machine down": "machine_down",
        "Network disconnection": "network_disconnection",
        "Disk full": "disk_full",
    }
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line.startswith("### "):
            workload = line[4:].strip().lower()
            fault = None
        elif line.endswith(":") and line[:-1] in fault_names:
            fault = fault_names[line[:-1]]
        elif line.startswith("+ application_"):
            if not workload or not fault:
                raise ValueError(f"Label without section context: {line}")
            application_id = line[2:].strip()
            if application_id in labels:
                raise ValueError(f"Duplicate Hadoop application label: {application_id}")
            labels[application_id] = {"workload": workload, "fault": fault}
    if not labels:
        raise ValueError(f"No Hadoop labels found in {path}")
    return labels


def _scan_hadoop_application(application_dir: Path, source_root: Path) -> dict[str, Any]:
    first_timestamp: str | None = None
    last_timestamp: str | None = None
    line_count = 0
    timestamped_lines = 0
    level_counts: Counter[str] = Counter()
    components: Counter[str] = Counter()
    decode_replacements = 0
    evidence: list[dict[str, Any]] = []
    templates: Counter[tuple[str, str, str]] = Counter()

    for log_path in sorted(application_dir.glob("*.log")):
        evidence.append(_evidence_ref(log_path, source_root))
        with log_path.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                line_count += 1
                decode_replacements += line.count("\ufffd")
                timestamp = HADOOP_TIMESTAMP_RE.match(line)
                if timestamp:
                    value = timestamp.group(1)
                    first_timestamp = min(first_timestamp or value, value)
                    last_timestamp = max(last_timestamp or value, value)
                    timestamped_lines += 1
                parsed = HADOOP_LOG_RE.match(line)
                if parsed:
                    level = parsed.group("level")
                    component = _component(parsed.group("logger"))
                    message = line[parsed.end():].strip()
                    template = _safe_template(message)
                    level_counts[level] += 1
                    components[component] += 1
                    templates[(level, component, template)] += 1

    return {
        "timestamps": (first_timestamp, last_timestamp),
        "line_count": line_count,
        "timestamped_lines": timestamped_lines,
        "level_counts": dict(sorted(level_counts.items())),
        "component_counts": dict(sorted(components.items())),
        "decode_replacements": decode_replacements,
        "evidence_refs": evidence,
        "templates": templates,
    }


def build_hadoop_records(dataset_dir: Path, source_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    labels_path = dataset_dir / "abnormal_label.txt"
    labels = parse_hadoop_labels(labels_path)
    application_dirs = {path.name: path for path in dataset_dir.glob("application_*") if path.is_dir()}
    missing_directories = sorted(set(labels) - set(application_dirs))
    unlabeled_directories = sorted(set(application_dirs) - set(labels))
    if missing_directories or unlabeled_directories:
        raise ValueError(
            f"Hadoop label/directory mismatch: missing={missing_directories}, unlabeled={unlabeled_directories}"
        )

    label_ref = _evidence_ref(labels_path, source_root)
    records: list[dict[str, Any]] = []
    for application_id, application_dir in sorted(application_dirs.items()):
        match = APPLICATION_RE.match(application_id)
        if not match:
            raise ValueError(f"Unexpected Hadoop application ID: {application_id}")
        cohort = match.group(1)
        label = labels[application_id]
        scan = _scan_hadoop_application(application_dir, source_root)
        fault = label["fault"]
        components = [name for name, count in scan["component_counts"].items() if count]
        safe_templates = []
        for (level, component, template), count in sorted(
                scan["templates"].items(), key=lambda item: (-item[1], item[0]))[:100]:
            template_hash = canonical_hash([application_id, level, component, template])
            safe_templates.append({
                "log_id": f"extlog_{template_hash[:24]}",
                "timestamp": scan["timestamps"][0],
                "level": level,
                "component": component,
                "redacted_message": template,
                "template_id": f"tpl_{canonical_hash(template)[:20]}",
                "count": count,
            })
        observed_signals = _signals(item["redacted_message"] for item in safe_templates)
        records.append(
            {
                "schema_version": SCHEMA_VERSION,
                "adapter_version": ADAPTER_VERSION,
                "dataset": "loghub_hadoop",
                "event_id": _event_id("loghub_hadoop", application_id),
                "source_unit_id": application_id,
                "group_id": f"hadoop_run_{cohort}",
                "cluster_alias": "cluster_loghub_hadoop_public",
                "product_version": None,
                "workload": label["workload"],
                "scenario_kind": "normal" if fault == "normal" else "injected_fault",
                "anomaly_label": "normal" if fault == "normal" else "anomaly",
                "injection_label": None if fault == "normal" else fault,
                "root_cause_label": None,
                "label_provenance": {
                    "kind": "dataset_declared_normal" if fault == "normal" else "injected_fault_family",
                    "confidence": "dataset_declared",
                    "source_ref": label_ref["ref_id"],
                },
                "timestamps": {
                    "start": scan["timestamps"][0],
                    "end": scan["timestamps"][1],
                    "format": "%Y-%m-%d %H:%M:%S,%f",
                    "timezone_source": None,
                    "semantics": "wall_clock_timezone_unknown",
                    "fault_start": None,
                    "first_observable_signal": None,
                },
                "components": sorted(components),
                "signals": observed_signals,
                "observations": {
                    "log_file_count": len(scan["evidence_refs"]),
                    "log_line_count": scan["line_count"],
                    "timestamped_line_count": scan["timestamped_lines"],
                    "level_counts": scan["level_counts"],
                    "component_counts": scan["component_counts"],
                    "decode_replacement_count": scan["decode_replacements"],
                    "safe_log_templates": safe_templates,
                },
                "evidence_refs": scan["evidence_refs"] + [label_ref],
                "benchmark_target": "injection_label",
                "metric_eligibility": {
                    "public_injection_benchmark": fault != "normal",
                    "production_root_cause_ranking": False,
                    "mttd": False,
                    "reasons": [
                        "root_cause_not_independently_confirmed",
                        "fault_start_unavailable",
                        "timezone_unknown",
                    ],
                },
            }
        )

    audit = {
        "schema_version": SCHEMA_VERSION,
        "dataset": "loghub_hadoop",
        "adapter_version": ADAPTER_VERSION,
        "source_units": len(records),
        "group_count": len({row["group_id"] for row in records}),
        "label_counts": dict(Counter(row["anomaly_label"] for row in records)),
        "injection_counts": dict(Counter(row["injection_label"] or "none" for row in records)),
        "workload_counts": dict(Counter(row["workload"] for row in records)),
        "log_file_count": sum(row["observations"]["log_file_count"] for row in records),
        "log_line_count": sum(row["observations"]["log_line_count"] for row in records),
        "missing_directories": missing_directories,
        "unlabeled_directories": unlabeled_directories,
        "raw_contains_host_and_network_identifiers": True,
        "normalized_exports_raw_messages": False,
        "product_version": None,
        "production_root_cause_metrics": "N/A",
        "mttd": "N/A",
        "limitations": [
            "controlled_fault_injection",
            "job_level_labels",
            "product_version_not_declared",
            "timezone_not_declared",
            "fault_start_not_declared",
        ],
    }
    return records, audit


def tracebench_family(scenario_name: str) -> str:
    parts = scenario_name.split("_")
    if len(parts) < 3 or parts[0] not in {"AN", "COM", "NM"}:
        raise ValueError(f"Unexpected TraceBench scenario name: {scenario_name}")
    return "_".join(parts[:3])


def _tracebench_labels(family: str) -> tuple[str, str, str | None, str]:
    if family.startswith("AN_"):
        return "injected_fault", "anomaly", TRACEBENCH_INJECTION_LABELS.get(family, family.lower()), "injected_fault_family"
    if family.startswith("NM_"):
        return "normal", "normal", None, "dataset_declared_normal"
    return "compound", "mixed", family.lower(), "compound_scenario_family"


def _tracebench_components(family: str) -> list[str]:
    lowered = family.lower()
    values: set[str] = set()
    if "dn" in lowered or "data_" in lowered:
        values.add("DataNode")
    if "cl_" in lowered:
        values.add("HDFS Client")
    if "hdfs" in lowered or family.startswith("COM_"):
        values.update(("HDFS Client", "NameNode", "DataNode"))
    if not values:
        values.add("cross-component")
    return sorted(values)


def _read_trace_summary(path: Path) -> dict[str, Any]:
    tasks = reports = edges = invalid_rows = 0
    first_seen: str | None = None
    last_updated: str | None = None
    titles: Counter[str] = Counter()
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as stream:
        for row in csv.DictReader(stream):
            try:
                reports += int(row["NumReports"])
                edges += int(row["NumEdges"])
            except (KeyError, TypeError, ValueError):
                invalid_rows += 1
                continue
            tasks += 1
            title = (row.get("Title") or "unknown").strip()
            titles[title] += 1
            start = (row.get("FirstSeen") or "").strip()
            end = (row.get("LastUpdated") or "").strip()
            if start:
                first_seen = min(first_seen or start, start)
            if end:
                last_updated = max(last_updated or end, end)
    return {
        "task_count": tasks,
        "report_count": reports,
        "edge_count": edges,
        "invalid_trace_rows": invalid_rows,
        "first_seen": first_seen,
        "last_updated": last_updated,
        "title_counts": dict(titles.most_common(20)),
    }


def _read_operation_summary(path: Path) -> dict[str, Any]:
    operation_types = invalid_rows = 0
    total_operations = 0
    operations: Counter[str] = Counter()
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as stream:
        for row in csv.DictReader(stream):
            try:
                count = int(row["Num"])
            except (KeyError, TypeError, ValueError):
                invalid_rows += 1
                continue
            name = (row.get("OpName") or "unknown").strip()
            operation_types += 1
            total_operations += count
            operations[name] += count
    return {
        "operation_type_count": operation_types,
        "operation_count": total_operations,
        "invalid_operation_rows": invalid_rows,
        "top_operations": dict(operations.most_common(20)),
    }


def _read_event_summary(path: Path) -> dict[str, Any]:
    component_counts: Counter[str] = Counter()
    failed = invalid = 0
    allowed = {
        "datanode": "DataNode",
        "namenode": "NameNode",
        "journalnode": "JournalNode",
        "dfsclient": "HDFS Client",
        "client": "HDFS Client",
    }
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as stream:
        for row in csv.DictReader(stream):
            if not row:
                invalid += 1
                continue
            agent = str(row.get("Agent") or "").casefold().replace(" ", "")
            component = next((value for key, value in allowed.items() if key in agent), None)
            if component:
                component_counts[component] += 1
            description = str(row.get("Description") or "").casefold()
            if any(token in description for token in ("fail", "error", "timeout", "exception")):
                failed += 1
    return {"component_counts": dict(sorted(component_counts.items())),
            "failed_event_count": failed, "invalid_event_rows": invalid}


def build_tracebench_records(dataset_dir: Path, source_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    tracebench_dir = dataset_dir / "tracebench"
    scenario_dirs = sorted(path for path in tracebench_dir.iterdir() if path.is_dir())
    records: list[dict[str, Any]] = []
    missing_files: list[str] = []

    for scenario_dir in scenario_dirs:
        required = [scenario_dir / name for name in ("trace.csv", "operation.csv", "edge.csv", "event.csv")]
        missing = [path.name for path in required if not path.is_file()]
        if missing:
            missing_files.append(f"{scenario_dir.name}: {','.join(missing)}")
            continue
        family = tracebench_family(scenario_dir.name)
        scenario_kind, anomaly_label, injection_label, label_kind = _tracebench_labels(family)
        trace = _read_trace_summary(scenario_dir / "trace.csv")
        operations = _read_operation_summary(scenario_dir / "operation.csv")
        events = _read_event_summary(scenario_dir / "event.csv")
        evidence = [_evidence_ref(path, source_root) for path in required]
        observed_components = sorted(events["component_counts"])
        records.append(
            {
                "schema_version": SCHEMA_VERSION,
                "adapter_version": ADAPTER_VERSION,
                "dataset": "hdfs_v3_tracebench",
                "event_id": _event_id("hdfs_v3_tracebench", scenario_dir.name),
                "source_unit_id": scenario_dir.name,
                "group_id": f"tracebench_family_{family.lower()}",
                "cluster_alias": "cluster_tracebench_public",
                "product_version": None,
                "workload": "trace_oriented_hdfs",
                "scenario_kind": scenario_kind,
                "anomaly_label": anomaly_label,
                "injection_label": injection_label,
                "root_cause_label": None,
                "label_provenance": {
                    "kind": label_kind,
                    "confidence": "dataset_declared",
                    "source_ref": "HDFS_v3_TraceBench/README.md",
                },
                "timestamps": {
                    "start": trace["first_seen"],
                    "end": trace["last_updated"],
                    "format": "%Y-%m-%d %H:%M:%S",
                    "timezone_source": None,
                    "semantics": "collector_wall_clock_timezone_unknown; span_ticks_have_unknown_origin",
                    "fault_start": None,
                    "first_observable_signal": None,
                },
                "components": observed_components or ["cross-component"],
                "signals": _signals([
                    *operations["top_operations"].keys(),
                    *observed_components,
                ]),
                "observations": {**trace, **operations, **events},
                "evidence_refs": evidence,
                "benchmark_target": "injection_label",
                "metric_eligibility": {
                    "public_injection_benchmark": scenario_kind != "normal",
                    "production_root_cause_ranking": False,
                    "mttd": False,
                    "reasons": [
                        "root_cause_not_independently_confirmed",
                        "fault_start_unavailable",
                        "timezone_unknown",
                        "span_tick_origin_unknown",
                    ],
                },
            }
        )

    if missing_files:
        raise ValueError(f"TraceBench scenarios missing required files: {missing_files}")
    audit = {
        "schema_version": SCHEMA_VERSION,
        "dataset": "hdfs_v3_tracebench",
        "adapter_version": ADAPTER_VERSION,
        "source_units": len(records),
        "group_count": len({row["group_id"] for row in records}),
        "scenario_counts": dict(Counter(row["scenario_kind"] for row in records)),
        "anomaly_label_counts": dict(Counter(row["anomaly_label"] for row in records)),
        "family_counts": dict(Counter(tracebench_family(row["source_unit_id"]) for row in records)),
        "task_count": sum(row["observations"]["task_count"] for row in records),
        "report_count": sum(row["observations"]["report_count"] for row in records),
        "edge_count": sum(row["observations"]["edge_count"] for row in records),
        "invalid_trace_rows": sum(row["observations"]["invalid_trace_rows"] for row in records),
        "invalid_operation_rows": sum(row["observations"]["invalid_operation_rows"] for row in records),
        "invalid_event_rows": sum(row["observations"]["invalid_event_rows"] for row in records),
        "raw_contains_host_and_network_identifiers": True,
        "normalized_exports_host_or_network_identifiers": False,
        "normalized_exports_raw_descriptions": False,
        "product_version": None,
        "production_root_cause_metrics": "N/A",
        "mttd": "N/A",
        "limitations": [
            "controlled_fault_injection_and_public_bug_scenarios",
            "scenario_name_is_not_an_independently_confirmed_root_cause",
            "product_version_not_declared",
            "timezone_not_declared",
            "fault_start_not_declared",
            "span_tick_origin_not_declared",
        ],
    }
    return records, audit


def _split_group_names(group_names: list[str], seed: int) -> dict[str, str]:
    ordered = sorted(group_names, key=lambda value: canonical_hash([seed, value]))
    count = len(ordered)
    if count < 3:
        return {name: "development" for name in ordered}
    development_count = max(1, round(count * 0.6))
    calibration_count = max(1, round(count * 0.2))
    if development_count + calibration_count >= count:
        development_count = count - 2
        calibration_count = 1
    result: dict[str, str] = {}
    for index, name in enumerate(ordered):
        if index < development_count:
            result[name] = "development"
        elif index < development_count + calibration_count:
            result[name] = "calibration"
        else:
            result[name] = "independent_test"
    return result


def assign_splits(records: list[dict[str, Any]], seed: int = DEFAULT_SEED) -> list[dict[str, Any]]:
    """Assign whole collection groups; no source unit or fault-script family is split."""
    assignments: dict[str, str] = {}
    hadoop_groups = sorted({row["group_id"] for row in records if row["dataset"] == "loghub_hadoop"})
    assignments.update(_split_group_names(hadoop_groups, seed))

    tracebench = [row for row in records if row["dataset"] == "hdfs_v3_tracebench"]
    for scenario_kind in sorted({row["scenario_kind"] for row in tracebench}):
        groups = sorted({row["group_id"] for row in tracebench if row["scenario_kind"] == scenario_kind})
        assignments.update(_split_group_names(groups, seed))

    rows = []
    for record in sorted(records, key=lambda value: (value["dataset"], value["event_id"])):
        split = assignments[record["group_id"]]
        rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "event_id": record["event_id"],
                "dataset": record["dataset"],
                "source_unit_id": record["source_unit_id"],
                "group_id": record["group_id"],
                "split": split,
                "record_sha256": canonical_hash(record),
                "public_labels_available": True,
                "strict_blind_eligible": False,
            }
        )
    return rows


def audit_split_assignments(records: list[dict[str, Any]], assignments: list[dict[str, Any]]) -> dict[str, Any]:
    event_ids = [row["event_id"] for row in records]
    assigned_ids = [row["event_id"] for row in assignments]
    group_membership: dict[str, set[str]] = {}
    for row in assignments:
        group_membership.setdefault(row["group_id"], set()).add(row["split"])
    group_cross_split = sorted(group for group, splits in group_membership.items() if len(splits) > 1)
    duplicate_records = sorted(key for key, count in Counter(event_ids).items() if count > 1)
    duplicate_events = sorted(key for key, count in Counter(assigned_ids).items() if count > 1)
    missing_events = sorted(set(event_ids) - set(assigned_ids))
    unknown_events = sorted(set(assigned_ids) - set(event_ids))
    record_by_id = {row["event_id"]: row for row in records}
    hash_mismatches = sorted(
        row["event_id"]
        for row in assignments
        if row["event_id"] in record_by_id and row["record_sha256"] != canonical_hash(record_by_id[row["event_id"]])
    )
    passed = not any(
        (group_cross_split, duplicate_records, duplicate_events, missing_events, unknown_events, hash_mismatches)
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol": "public_group_isolated_v1",
        "passed": passed,
        "event_count": len(records),
        "assignment_count": len(assignments),
        "split_counts": dict(Counter(row["split"] for row in assignments)),
        "dataset_split_counts": {
            dataset: dict(Counter(row["split"] for row in assignments if row["dataset"] == dataset))
            for dataset in sorted({row["dataset"] for row in assignments})
        },
        "group_cross_split": group_cross_split,
        "duplicate_source_records": duplicate_records,
        "duplicate_events": duplicate_events,
        "missing_events": missing_events,
        "unknown_events": unknown_events,
        "record_hash_mismatches": hash_mismatches,
        "public_labels_available": True,
        "strict_blind_eligible": False,
        "warning": "The public independent_test partition is group-isolated but not a sealed blind test.",
    }


def build_diagnostic_snapshot(record: dict[str, Any]) -> dict[str, Any]:
    """Build the label-free object consumed by the service and Agent."""
    ExternalEventV12.model_validate(record)
    evidence = [item for item in record["evidence_refs"]
                if not str(item.get("relative_path") or "").endswith("abnormal_label.txt")]
    trace_summary = None
    log_templates = record["observations"].get("safe_log_templates", [])
    if record["dataset"] == "hdfs_v3_tracebench":
        observations = record["observations"]
        trace_summary = {
            "task_count": observations["task_count"],
            "report_count": observations["report_count"],
            "edge_count": observations["edge_count"],
            "operation_count": observations["operation_count"],
            "operation_type_count": observations["operation_type_count"],
            "failed_event_count": observations["failed_event_count"],
            "component_counts": observations["component_counts"],
            "top_operations": observations["top_operations"],
        }
    value = {
        "schema_version": 1,
        "adapter_version": record["adapter_version"],
        "event_id": record["event_id"],
        "dataset": record["dataset"],
        "source_type": "public_dataset",
        "cluster_alias": record["cluster_alias"],
        "product_version": record["product_version"],
        "components": record["components"],
        "observation_window": {
            "start": record["timestamps"].get("start"),
            "end": record["timestamps"].get("end"),
        },
        "log_templates": log_templates,
        "trace_summary": trace_summary,
        "signals": record["signals"],
        "evidence_refs": evidence,
    }
    value["snapshot_hash"] = canonical_hash(value)
    return DiagnosticSnapshotV12.model_validate(value).model_dump(mode="json")


def build_evaluation_label(record: dict[str, Any], split: str) -> dict[str, Any]:
    value = {
        "schema_version": 1,
        "event_id": record["event_id"],
        "dataset": record["dataset"],
        "group_id": record["group_id"],
        "split": split,
        "anomaly_label": record["anomaly_label"],
        "injection_label": record["injection_label"],
        "root_cause_label": None,
        "metric_eligibility": record["metric_eligibility"],
    }
    return EvaluationLabelV12.model_validate(value).model_dump(mode="json")


def _verify_download_manifest(source_root: Path) -> dict[str, Any]:
    manifest_path = source_root / "DOWNLOAD_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for archive in manifest["archives"]:
        archive_path = source_root / archive["archive"]
        if archive_path.stat().st_size != archive["bytes"]:
            raise ValueError(f"Archive size mismatch: {archive_path}")
        if md5_file(archive_path) != archive["md5"]:
            raise ValueError(f"Archive MD5 mismatch: {archive_path}")
    return manifest


def _dataset_manifest(output_dir: Path, records: list[dict[str, Any]], audit: dict[str, Any]) -> dict[str, Any]:
    events_path = output_dir / "events.jsonl"
    audit_path = output_dir / "dataset_audit.json"
    _write_jsonl(events_path, records)
    _write_json(audit_path, audit)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "adapter_version": ADAPTER_VERSION,
        "dataset": audit["dataset"],
        "record_count": len(records),
        "artifacts": {
            "events.jsonl": sha256_file(events_path),
            "dataset_audit.json": sha256_file(audit_path),
        },
        "raw_data_mutated": False,
    }
    _write_json(output_dir / "manifest.json", manifest)
    return manifest


def prepare_external_datasets(source_root: Path, seed: int = DEFAULT_SEED) -> dict[str, Any]:
    source_root = source_root.resolve()
    download_manifest = _verify_download_manifest(source_root)
    processed_root = source_root / "processed"
    split_root = source_root / "splits"
    _atomic_text(
        processed_root / "README.md",
        "# v1.2 标准化公开数据\n\n"
        "`hadoop/events.jsonl` 以 Hadoop application 为事件；"
        "`tracebench/events.jsonl` 以 TraceBench 场景目录为事件。\n\n"
        "记录只包含统计量、公开标签和证据文件 SHA-256，不包含原始日志、IP、主机名或描述文本。"
        "注入故障标签与生产根因标签严格分开，生产根因指标和 MTTD 保持 `N/A`。\n",
    )
    _atomic_text(
        split_root / "README.md",
        "# v1.2 公开数据切分\n\n"
        "`development.jsonl`、`calibration.jsonl` 和 `independent_test.jsonl` 保存事件归属。"
        "同一 Hadoop 运行批次或 TraceBench 场景族不会跨分区。\n\n"
        "这些数据和标签均为公开信息，因此 independent_test 是组隔离测试分区，"
        "不属于封存盲测集。正式候选验收仍需另建未见测试集。\n",
    )

    hadoop_records, hadoop_audit = build_hadoop_records(source_root / "Hadoop", source_root)
    tracebench_records, tracebench_audit = build_tracebench_records(
        source_root / "HDFS_v3_TraceBench", source_root
    )
    hadoop_manifest = _dataset_manifest(processed_root / "hadoop", hadoop_records, hadoop_audit)
    tracebench_manifest = _dataset_manifest(
        processed_root / "tracebench", tracebench_records, tracebench_audit
    )

    records = hadoop_records + tracebench_records
    assignments = assign_splits(records, seed=seed)
    split_audit = audit_split_assignments(records, assignments)
    if not split_audit["passed"]:
        raise ValueError(f"Split leakage audit failed: {split_audit}")
    for split in ("development", "calibration", "independent_test"):
        _write_jsonl(split_root / f"{split}.jsonl", [row for row in assignments if row["split"] == split])
    _write_jsonl(split_root / "assignments.jsonl", assignments)
    _write_json(split_root / "leakage_audit.json", split_audit)
    split_manifest = {
        "schema_version": SCHEMA_VERSION,
        "protocol": "public_group_isolated_v1",
        "seed": seed,
        "public_labels_available": True,
        "strict_blind_eligible": False,
        "artifacts": {
            path.name: sha256_file(path)
            for path in sorted(split_root.glob("*.json*"))
            if path.name != "manifest.json"
        },
    }
    _write_json(split_root / "manifest.json", split_manifest)

    assignment_by_event = {row["event_id"]: row for row in assignments}
    snapshots = [build_diagnostic_snapshot(row) for row in records]
    labels = [build_evaluation_label(
        row, assignment_by_event[row["event_id"]]["split"]) for row in records]
    snapshots_path = processed_root / "diagnostic_snapshots.jsonl"
    labels_path = processed_root / "evaluation_labels.jsonl"
    _write_jsonl(snapshots_path, snapshots)
    _write_jsonl(labels_path, labels)

    result = {
        "schema_version": SCHEMA_VERSION,
        "adapter_version": ADAPTER_VERSION,
        "source_record_id": download_manifest["source"]["record_id"],
        "source_archives_verified": True,
        "raw_data_mutated": False,
        "records": {
            "loghub_hadoop": len(hadoop_records),
            "hdfs_v3_tracebench": len(tracebench_records),
            "total": len(records),
        },
        "split_counts": split_audit["split_counts"],
        "production_root_cause_metrics": "N/A",
        "mttd": "N/A",
        "manifests": {
            "hadoop": hadoop_manifest,
            "tracebench": tracebench_manifest,
            "splits": split_manifest,
        },
        "label_separation": {
            "diagnostic_snapshots": sha256_file(snapshots_path),
            "evaluation_labels": sha256_file(labels_path),
            "agent_input_contains_labels": False,
        },
    }
    _write_json(source_root / "processing_manifest.json", result)
    return result


def audit_external_outputs(source_root: str | Path) -> dict[str, Any]:
    source_root = Path(source_root).resolve()
    manifest_path = source_root / "processing_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    processed = source_root / "processed"
    snapshots_path = processed / "diagnostic_snapshots.jsonl"
    labels_path = processed / "evaluation_labels.jsonl"
    snapshots = [DiagnosticSnapshotV12.model_validate_json(line)
                 for line in snapshots_path.read_text(encoding="utf-8").splitlines() if line]
    labels = [EvaluationLabelV12.model_validate_json(line)
              for line in labels_path.read_text(encoding="utf-8").splitlines() if line]
    snapshot_ids = {row.event_id for row in snapshots}
    label_ids = {row.event_id for row in labels}
    encoded_snapshots = snapshots_path.read_text(encoding="utf-8").casefold()
    forbidden = [name for name in ("injection_label", "root_cause_label", "scenario_kind",
                                    "source_unit_id", "label_provenance")
                 if name in encoded_snapshots]
    expected = manifest["label_separation"]
    hash_mismatches = []
    if sha256_file(snapshots_path) != expected["diagnostic_snapshots"]:
        hash_mismatches.append("diagnostic_snapshots.jsonl")
    if sha256_file(labels_path) != expected["evaluation_labels"]:
        hash_mismatches.append("evaluation_labels.jsonl")
    result = {
        "schema_version": 1,
        "passed": snapshot_ids == label_ids and not forbidden and not hash_mismatches,
        "snapshot_count": len(snapshots),
        "label_count": len(labels),
        "missing_snapshots": sorted(label_ids - snapshot_ids),
        "missing_labels": sorted(snapshot_ids - label_ids),
        "forbidden_label_fields_in_snapshots": forbidden,
        "hash_mismatches": hash_mismatches,
        "production_root_cause_metrics": "N/A",
        "mttd": "N/A",
    }
    return result
