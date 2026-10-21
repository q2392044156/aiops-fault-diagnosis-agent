"""Immutable release manifest for the opt-in framework flow candidate."""

import json
import os
import shutil
import tomllib
import uuid
from pathlib import Path

from aiops_diag.agent_v11.engine import CANDIDATE_REPORT_PROMPT
from aiops_diag.agent_v11.release import verify as verify_v11
from aiops_diag.data.common import digest, key, save, verified_manifest


PRODUCT_VERSION = "v1.1-framework-rc2"
AGENT_VERSION = "agent_v0.4.1_langgraph"
RAG_VERSION = "rag_v0.3.1_query_builder"


def _base(agent_cfg, v11):
    return verify_v11(agent_cfg, v11["protocol"], v11["calibration"],
                      v11["base_service_config"], v11["release_dir"])


def _code_hashes():
    package = Path(__file__).resolve().parents[1]
    paths = [*Path(__file__).resolve().parent.glob("*.py"),
             package / "agent_v11" / "engine.py",
             package / "service" / "config.py",
             package / "service" / "runtime.py"]
    return {str(path.relative_to(package)).replace("\\", "/"): digest(path)
            for path in sorted(paths)}


def _dependencies(agent_cfg):
    root = Path(agent_cfg["root"])
    return {name: digest(root / name) for name in (
        "requirements-service-lock.txt", "requirements-framework.in",
        "requirements-framework-lock.txt")}


def _deployment(agent_cfg):
    root = Path(agent_cfg["root"])
    names = ("deployment/Dockerfile", "deployment/compose.framework-rc2.yaml",
             "deployment/compose.legacy-rollback-rc2.yaml", ".dockerignore")
    return {name: digest(root / name) for name in names}


def _package(agent_cfg):
    path = Path(agent_cfg["root"]) / "pyproject.toml"
    version = tomllib.loads(path.read_text(encoding="utf-8"))["project"]["version"]
    return version, digest(path)


def _prior_observation(path):
    path = Path(path)
    result = json.loads(path.read_text(encoding="utf-8"))
    if result.get("status") != "INDEPENDENT_RETRIEVAL_EVALUATION":
        raise ValueError("Prior blind observation has an unexpected status")
    candidate = result.get("candidate", {}).get("counts", {})
    return {
        "sha256": digest(path),
        "source_candidate_release_id": result.get("candidate_release_id"),
        "query_count": candidate.get("queries"),
        "no_answer_count": candidate.get("no_answer"),
        "no_answer_false_return_count": candidate.get(
            "no_answer_false_return_count"),
        "no_answer_false_return_rate": candidate.get("no_answer_false_return_rate"),
        "answer_false_refusal_count": candidate.get("answer_false_refusal_count"),
        "revealed": True,
        "reusable_for_tuning_or_acceptance": False,
    }


def _value(agent_cfg, v11, framework, service_config_path):
    base = _base(agent_cfg, {**v11,
        "base_service_config": framework["base_service_config"]})
    package_version, pyproject_hash = _package(agent_cfg)
    value = {
        "schema_version": 1,
        "product_version": PRODUCT_VERSION,
        "package_version": package_version,
        "pyproject_sha256": pyproject_hash,
        "status": "READY_FOR_FLOW_VALIDATION",
        "production_ready": False,
        "quality_gate_policy": "record_only_for_framework_flow",
        "agent_version": AGENT_VERSION,
        "rag_version": RAG_VERSION,
        "kb_release_id": base["kb_release_id"],
        "gate_strategy": base["gate_strategy"],
        "gate_threshold": base["gate_threshold"],
        "query_builder": base["query_builder"],
        "tool_manifest_hash": base["tool_manifest_hash"],
        "risk_policy_hash": base["risk_policy_hash"],
        "prompt_version": "v12_langchain_summary_v1",
        "prompt_hash": key(CANDIDATE_REPORT_PROMPT),
        "execution_backend": "langgraph",
        "report_backend": "langchain",
        "retrieval_backend": "langchain",
        "checkpoint_backend": "database_authority_no_langgraph_checkpointer",
        "base_release_id": base["release_id"],
        "base_release_hash": key(base),
        "service_config_sha256": digest(service_config_path),
        "dependency_hashes": _dependencies(agent_cfg),
        "deployment_hashes": _deployment(agent_cfg),
        "code_hashes": _code_hashes(),
        "prior_blind_observation": _prior_observation(
            framework["prior_blind_observation"]),
    }
    value["candidate_hash"] = key(value)
    value["release_id"] = "agrfw_" + value["candidate_hash"][:24]
    return value


def publish(agent_cfg, v11, framework, service_config_path, directory):
    value = _value(agent_cfg, v11, framework, service_config_path)
    directory = Path(directory)
    if directory.exists():
        existing = verify(agent_cfg, v11, framework, service_config_path, directory,
                          strict_source=True)
        if existing != value:
            raise ValueError("Existing framework candidate differs; use a new directory")
        return existing
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


def verify(agent_cfg, v11, framework, service_config_path, directory,
           strict_source=False):
    directory = Path(directory)
    verified_manifest(directory, "manifest.json")
    actual = json.loads((directory / "framework_candidate.json").read_text(
        encoding="utf-8"))
    identity = dict(actual)
    release_id = identity.pop("release_id", None)
    candidate_hash = identity.pop("candidate_hash", None)
    if (candidate_hash != key(identity)
            or release_id != "agrfw_" + candidate_hash[:24]
            or actual.get("product_version") != PRODUCT_VERSION):
        raise ValueError("Framework candidate release identity changed")
    if strict_source:
        expected = _value(agent_cfg, v11, framework, service_config_path)
        if actual != expected:
            raise ValueError("Framework candidate source or frozen input changed")
    return actual


if __name__ == "__main__":
    import argparse

    from aiops_diag.service.config import load

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service_config", type=Path)
    parser.add_argument("output_dir", type=Path)
    options = parser.parse_args()
    cfg = load(options.service_config)
    framework = publish(cfg["agent"], cfg["v11_candidate"],
                        cfg["framework_candidate"], cfg["config_path"],
                        options.output_dir)
    print(json.dumps({"release_id": framework["release_id"],
                      "status": framework["status"]}, ensure_ascii=False))
