"""Immutable release metadata for the v1.2 checkpoint and public-data candidate."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path

from aiops_diag.data.common import digest, key, save, verified_manifest


PRODUCT_VERSION = "v1.2-rc1"
PACKAGE_VERSION = "1.2.0rc1"
AGENT_VERSION = "agent_v0.5.0_langgraph"
GRAPH_VERSION = "graph_v1.2_checkpoint_v1"
DATA_ADAPTER_VERSION = "v12_open_data_v1"
V12_TOOLS = [
    "detect_anomaly", "query_logs", "read_trace_summary", "query_metrics",
    "search_similar_incidents", "retrieve_runbook", "rank_root_causes",
    "generate_incident_report", "request_human_approval",
]


def _value(cfg):
    root = Path(cfg["root"])
    base_dir = Path(cfg["framework_candidate"]["release_dir"])
    verified_manifest(base_dir, "manifest.json")
    base = json.loads((base_dir / "framework_candidate.json").read_text(encoding="utf-8"))
    package = root / "pyproject.toml"
    protocol_dir = root / "evaluation/v1.2/real_incident_protocol"
    data_protocol_dir = root / "evaluation/v1.2/external_open_datasets"
    code_paths = [
        root / "src/aiops_diag/framework_v12/graph.py",
        root / "src/aiops_diag/framework_v12/checkpoint.py",
        root / "src/aiops_diag/framework_v12/tools_v12.py",
        root / "src/aiops_diag/framework_v12/evaluation.py",
        root / "src/aiops_diag/framework_v12/release_v12.py",
        root / "src/aiops_diag/data/v12_contracts.py",
        root / "src/aiops_diag/data/v12_external.py",
        root / "src/aiops_diag/data/v12_import.py",
        root / "src/aiops_diag/data/incident_v12.py",
        root / "src/aiops_diag/data/__main__.py",
        root / "src/aiops_diag/agent_v11/engine.py",
        root / "src/aiops_diag/agent/engine.py",
        root / "src/aiops_diag/agent/schemas.py",
        root / "src/aiops_diag/service/db.py",
        root / "src/aiops_diag/service/config.py",
        root / "src/aiops_diag/service/runtime.py",
        root / "scripts/evaluate_v12.py",
        root / "scripts/validate_v12_online.py",
    ]
    dependency_paths = [
        root / "requirements-lock.txt",
        root / "requirements-service-lock.txt",
        root / "requirements-framework-lock.txt",
    ]
    deployment_paths = [
        root / "deployment/Dockerfile",
        root / "deployment/compose.yaml",
        root / "deployment/compose.v12-rc1.yaml",
        root / "deployment/compose.v12-rollback.yaml",
        root / ".dockerignore",
    ]
    evaluation_paths = [
        root / "evaluation/v1.2/v12_rc1_validation/result.json",
        root / "evaluation/v1.2/v12_rc1_validation/report.md",
        root / "evaluation/v1.2/v12_rc1_validation/online.json",
        root / "deliverables/v1.2_RC1_实施报告.md",
    ]
    data_manifest = root / "data/external/loghub/processing_manifest.json"
    value = {
        "schema_version": 2,
        "product_version": PRODUCT_VERSION,
        "package_version": PACKAGE_VERSION,
        "status": "IMPLEMENTATION_CANDIDATE",
        "production_ready": False,
        "agent_version": AGENT_VERSION,
        "graph_version": GRAPH_VERSION,
        "rag_version": base["rag_version"],
        "query_builder": base["query_builder"],
        "data_adapter_version": DATA_ADAPTER_VERSION,
        "incident_protocol_version": "real_incident_v1",
        "report_schema_version": 2,
        "checkpoint_backend": "sqlite_database_authority_v1",
        "execution_backend": "langgraph",
        "report_backend": "langchain",
        "retrieval_backend": "langchain",
        "kb_release_id": base["kb_release_id"],
        "gate_strategy": base["gate_strategy"],
        "gate_threshold": base["gate_threshold"],
        "tool_manifest": V12_TOOLS,
        "tool_manifest_hash": key(V12_TOOLS),
        "risk_policy_hash": base["risk_policy_hash"],
        "prompt_version": base["prompt_version"],
        "prompt_hash": base["prompt_hash"],
        "base_release_id": base["release_id"],
        "base_release_hash": key(base),
        "service_config_sha256": digest(cfg["config_path"]),
        "pyproject_sha256": digest(package),
        "dependency_hashes": {
            str(path.relative_to(root)).replace("\\", "/"): digest(path)
            for path in dependency_paths
        },
        "deployment_hashes": {
            str(path.relative_to(root)).replace("\\", "/"): digest(path)
            for path in deployment_paths
        },
        "evaluation_hashes": {
            str(path.relative_to(root)).replace("\\", "/"): digest(path)
            for path in evaluation_paths
        },
        "external_data_manifest_sha256": (digest(data_manifest)
                                                  if data_manifest.is_file() else None),
        "code_hashes": {str(path.relative_to(root)).replace("\\", "/"): digest(path)
                        for path in code_paths},
        "protocol_hashes": {
            str(path.relative_to(root)).replace("\\", "/"): digest(path)
            for directory in (protocol_dir, data_protocol_dir)
            for path in sorted(directory.glob("*")) if path.is_file()
        },
        "data_policy": {
            "public_injection_labels_are_production_root_causes": False,
            "production_root_cause_metrics": "N/A",
            "mttd": "N/A",
            "public_independent_test_is_strict_blind": False,
        },
    }
    value["candidate_hash"] = key(value)
    value["release_id"] = "agr12_" + value["candidate_hash"][:24]
    return value


def publish(cfg, directory):
    value = _value(cfg)
    directory = Path(directory)
    if directory.exists():
        actual = verify(cfg, directory, strict_source=True)
        if actual != value:
            raise ValueError("Existing v1.2 release differs; use a new directory")
        return actual
    directory.parent.mkdir(parents=True, exist_ok=True)
    staging = directory.parent / f".{directory.name}.{uuid.uuid4().hex}.partial"
    try:
        staging.mkdir()
        save(staging / "framework_candidate.json", value)
        save(staging / "manifest.json", {"schema_version": 1, "artifacts": {
            "framework_candidate.json": digest(staging / "framework_candidate.json")}})
        verified_manifest(staging, "manifest.json")
        os.replace(staging, directory)
    finally:
        if staging.exists() and staging.resolve().parent == directory.parent.resolve():
            shutil.rmtree(staging)
    return value


def verify(cfg, directory, strict_source=False):
    directory = Path(directory)
    verified_manifest(directory, "manifest.json")
    actual = json.loads((directory / "framework_candidate.json").read_text(encoding="utf-8"))
    identity = dict(actual)
    release_id = identity.pop("release_id", None)
    candidate_hash = identity.pop("candidate_hash", None)
    if (candidate_hash != key(identity) or release_id != "agr12_" + candidate_hash[:24]
            or actual.get("product_version") != PRODUCT_VERSION):
        raise ValueError("v1.2 release identity changed")
    if strict_source and actual != _value(cfg):
        raise ValueError("v1.2 source or frozen input changed")
    return actual
