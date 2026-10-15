import json
from pathlib import Path

from aiops_diag.data.common import digest, key, save, verified_manifest
from aiops_diag.rag.release import verify as verify_rag


TOOLS = [
    "detect_anomaly", "query_logs", "query_metrics", "search_similar_incidents",
    "retrieve_runbook", "rank_root_causes", "generate_incident_report",
    "request_human_approval",
]
RISK_POLICY = {
    "always_review": ["high_risk", "unknown_action", "low_confidence",
                      "unknown_confidence", "conflicting_evidence", "version_mismatch",
                      "prompt_injection", "budget_exhausted", "tool_failure"],
    "execution_allowed": False,
}


def code_hashes():
    directory = Path(__file__).resolve().parent
    return {path.name: digest(path) for path in sorted(directory.glob("*.py"))}


def publish(cfg):
    rag = verify_rag(cfg["rag"])
    release = {
        "schema_version": 1,
        "product_version": "v1.0",
        "agent_version": cfg["agent_version"],
        "config_hash": cfg["config_hash"],
        "rag_version": rag["rag_version"],
        "kb_release_id": rag["kb_release_id"],
        "rag_release_hash": key(rag),
        "tool_manifest": TOOLS,
        "tool_manifest_hash": key(TOOLS),
        "risk_policy": RISK_POLICY,
        "risk_policy_hash": key(RISK_POLICY),
        "prompt_version": "w9_agent_prompt_v1",
        "evaluation_hashes": {
            "adev": digest(cfg["paths"]["adev"]),
            "atest": digest(cfg["paths"]["atest"]),
        },
        "code_hashes": code_hashes(),
    }
    release["candidate_hash"] = key(release)
    release["release_id"] = "agr_" + key(release)[:24]
    directory = Path(cfg["paths"]["release_dir"])
    directory.mkdir(parents=True, exist_ok=True)
    save(directory / "agent_release.json", release)
    registry = {"schema_version": 1, "agent_version": cfg["agent_version"],
                "artifacts": {"agent_release.json": digest(
                    directory / "agent_release.json")}}
    save(directory / "manifest.json", registry)
    verified_manifest(directory, "manifest.json")
    return release


def verify(cfg):
    directory = Path(cfg["paths"]["release_dir"])
    verified_manifest(directory, "manifest.json")
    release = json.loads((directory / "agent_release.json").read_text(encoding="utf-8"))
    if release.get("agent_version") != cfg["agent_version"]:
        raise ValueError("Agent release version changed")
    if release.get("product_version") != "v1.0":
        raise ValueError("Agent product version changed")
    if release.get("config_hash") != cfg["config_hash"]:
        raise ValueError("Agent configuration changed after publication")
    if release.get("tool_manifest_hash") != key(TOOLS):
        raise ValueError("Agent tool manifest changed")
    if release.get("risk_policy_hash") != key(RISK_POLICY):
        raise ValueError("Agent risk policy changed")
    if release.get("code_hashes") != code_hashes():
        raise ValueError("Agent source code changed after publication")
    expected_evaluations = {"adev": digest(cfg["paths"]["adev"]),
                            "atest": digest(cfg["paths"]["atest"])}
    if release.get("evaluation_hashes") != expected_evaluations:
        raise ValueError("Agent evaluation protocol changed after publication")
    rag = verify_rag(cfg["rag"])
    if release.get("rag_release_hash") != key(rag):
        raise ValueError("Agent upstream RAG release changed")
    return release
