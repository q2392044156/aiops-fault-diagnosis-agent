"""Hash-bound research candidate layered over the frozen v1.0 Agent release."""

import json
import os
import shutil
import tomllib
import uuid
from pathlib import Path

import yaml

from aiops_diag.agent.release import verify as verify_legacy
from aiops_diag.data.common import digest, key, save, verified_manifest
from aiops_diag.retrieval.gate_v11 import calibrate_candidate
from aiops_diag.retrieval.protocol_v11 import validate_protocol
from aiops_diag.retrieval.release import FrozenRetriever

from .engine import CANDIDATE_REPORT_PROMPT


def _code_hashes():
    package = Path(__file__).resolve().parents[1]
    paths = [*Path(__file__).resolve().parent.glob("*.py"),
             package / "retrieval" / "gate_v11.py",
             package / "retrieval" / "protocol_v11.py",
             package / "retrieval" / "blind_v11.py",
             package / "retrieval" / "evaluation.py",
             package / "service" / "config.py",
             package / "service" / "runtime.py"]
    return {str(path.relative_to(package)).replace("\\", "/"): digest(path)
            for path in sorted(paths)}


def _inputs(agent_cfg, protocol_path, calibration_path):
    legacy = verify_legacy(agent_cfg)
    protocol_path, calibration_path = Path(protocol_path), Path(calibration_path)
    protocol = validate_protocol(protocol_path)
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    if (calibration.get("status") != "calibration_only"
            or calibration.get("protocol_sha256") != digest(protocol_path)
            or calibration.get("kb_release_id") != legacy["kb_release_id"]
            or calibration.get("gate_strategy") != "top_result_dense_v11"):
        raise ValueError("Candidate calibration does not match frozen inputs")
    maximum_false_rate = float(calibration.get("maximum_false_rate_target", 1.0))
    if not 0.0 <= maximum_false_rate <= 0.10:
        raise ValueError("Candidate no-answer calibration target is invalid")
    recalculated = calibrate_candidate(
        FrozenRetriever(agent_cfg["rag"]["retrieval"]), protocol_path,
        maximum_false_rate)
    if abs(float(calibration["gate_threshold"]) - recalculated["gate_threshold"]) > 1e-9:
        raise ValueError("Candidate gate threshold was not reproduced")
    stable_metrics = ("query_count", "recall", "mrr", "ndcg", "answer_coverage",
                      "answer_false_refusal", "no_answer_refusal", "no_answer_false_return")
    for split in ("development", "calibration"):
        claimed = calibration.get("metrics", {}).get(split, {})
        actual = recalculated["metrics"][split]
        if any(claimed.get(name) != actual[name] for name in stable_metrics):
            raise ValueError(f"Candidate {split} metrics were not reproduced")
    return legacy, protocol, calibration


def _package_metadata(agent_cfg):
    path = Path(agent_cfg["root"]) / "pyproject.toml"
    version = tomllib.loads(path.read_text(encoding="utf-8"))["project"]["version"]
    if version != "1.1.0rc2":
        raise ValueError("Candidate package version must be 1.1.0rc2")
    return version, digest(path)


def _dependency_hashes(agent_cfg):
    root = Path(agent_cfg["root"])
    return {name: digest(root / name) for name in (
        "requirements-lock.txt", "requirements-service-lock.txt")}


def _deployment_hashes(agent_cfg):
    root = Path(agent_cfg["root"])
    values = {f"deployment/{name}": digest(root / "deployment" / name)
              for name in ("compose.framework-rc2.yaml",
                           "compose.legacy-rollback-rc2.yaml", "Dockerfile")}
    values[".dockerignore"] = digest(root / ".dockerignore")
    return values


def _query_builder(service_config_path):
    service_path = Path(service_config_path).resolve()
    raw = yaml.safe_load(service_path.read_text(encoding="utf-8"))
    relative = raw.get("query_builder_config")
    if not relative:
        raise ValueError("RC2 service config requires query_builder_config")
    root = service_path.parent.parent
    path = (root / relative).resolve()
    from .query_builder import load_config

    cfg = load_config(path)
    return {"version": cfg["builder_version"],
            "config_sha256": cfg["config_sha256"],
            "max_plans": cfg["max_plans"]}


def publish(agent_cfg, protocol_path, calibration_path, service_config_path, directory):
    legacy, protocol, calibration = _inputs(agent_cfg, protocol_path, calibration_path)
    package_version, pyproject_hash = _package_metadata(agent_cfg)
    query_builder = _query_builder(service_config_path)
    value = {"schema_version": 1, "product_version": "v1.1-rc2",
             "package_version": package_version, "pyproject_sha256": pyproject_hash,
             "dependency_hashes": _dependency_hashes(agent_cfg),
             "status": ("READY_FOR_ACCEPTANCE" if protocol["release_ready"]
                        else "RESEARCH_CANDIDATE"),
             "agent_version": "agent_v0.3.1_query_builder",
             "rag_version": "rag_v0.2.1_query_builder",
             "kb_release_id": legacy["kb_release_id"],
             "tool_manifest_hash": legacy["tool_manifest_hash"],
             "risk_policy_hash": legacy["risk_policy_hash"],
             "prompt_version": "v11_evidence_gate_report_v1",
             "prompt_hash": key(CANDIDATE_REPORT_PROMPT),
             "legacy_release_hash": key(legacy),
             "service_config_sha256": digest(service_config_path),
             "protocol_sha256": digest(protocol_path),
             "calibration_sha256": digest(calibration_path),
             "gate_strategy": calibration["gate_strategy"],
             "gate_threshold": calibration["gate_threshold"],
             "query_builder": query_builder,
             "deployment_hashes": _deployment_hashes(agent_cfg),
             "code_hashes": _code_hashes()}
    value["candidate_hash"] = key(value)
    value["release_id"] = "agr11_" + value["candidate_hash"][:24]
    directory = Path(directory)
    if directory.exists():
        existing = verify(agent_cfg, protocol_path, calibration_path,
                          service_config_path, directory)
        if existing != value:
            raise ValueError("Existing candidate differs; choose a new release directory")
        return existing
    directory.parent.mkdir(parents=True, exist_ok=True)
    staging = directory.parent / f".{directory.name}.{uuid.uuid4().hex}.partial"
    try:
        staging.mkdir()
        save(staging / "agent_v11_candidate.json", value)
        save(staging / "manifest.json", {"schema_version": 1,
             "artifacts": {"agent_v11_candidate.json": digest(
                 staging / "agent_v11_candidate.json")}})
        verified_manifest(staging, "manifest.json")
        os.replace(staging, directory)
    finally:
        if staging.exists() and staging.resolve().parent == directory.parent.resolve():
            shutil.rmtree(staging)
    return value


def verify(agent_cfg, protocol_path, calibration_path, service_config_path, directory):
    legacy, protocol, calibration = _inputs(agent_cfg, protocol_path, calibration_path)
    package_version, pyproject_hash = _package_metadata(agent_cfg)
    directory = Path(directory)
    verified_manifest(directory, "manifest.json")
    value = json.loads((directory / "agent_v11_candidate.json").read_text(encoding="utf-8"))
    identity = dict(value)
    release_id = identity.pop("release_id", None)
    candidate_hash = identity.pop("candidate_hash", None)
    if candidate_hash != key(identity) or release_id != "agr11_" + candidate_hash[:24]:
        raise ValueError("Candidate release identity changed")
    if (value.get("product_version") != "v1.1-rc2"
            or value.get("agent_version") != "agent_v0.3.1_query_builder"
            or value.get("prompt_hash") != key(CANDIDATE_REPORT_PROMPT)
            or value.get("package_version") != package_version
            or value.get("pyproject_sha256") != pyproject_hash
            or value.get("dependency_hashes") != _dependency_hashes(agent_cfg)
            or value.get("legacy_release_hash") != key(legacy)
            or value.get("service_config_sha256") != digest(service_config_path)
            or value.get("protocol_sha256") != digest(protocol_path)
            or value.get("calibration_sha256") != digest(calibration_path)
            or value.get("gate_strategy") != calibration["gate_strategy"]
            or value.get("gate_threshold") != calibration["gate_threshold"]
            or value.get("query_builder") != _query_builder(service_config_path)
            or value.get("deployment_hashes") != _deployment_hashes(agent_cfg)
            or value.get("code_hashes") != _code_hashes()):
        raise ValueError("Candidate source or frozen input changed")
    expected_status = "READY_FOR_ACCEPTANCE" if protocol["release_ready"] else "RESEARCH_CANDIDATE"
    if value["status"] != expected_status:
        raise ValueError("Candidate review status changed")
    return value


if __name__ == "__main__":
    import argparse

    from aiops_diag.agent.config import load

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("agent_config", type=Path)
    parser.add_argument("protocol", type=Path)
    parser.add_argument("calibration", type=Path)
    parser.add_argument("service_config", type=Path)
    parser.add_argument("output_dir", type=Path)
    options = parser.parse_args()
    candidate = publish(load(options.agent_config), options.protocol,
                        options.calibration, options.service_config,
                        options.output_dir)
    print(json.dumps({"release_id": candidate["release_id"],
                      "status": candidate["status"]}, ensure_ascii=False))
