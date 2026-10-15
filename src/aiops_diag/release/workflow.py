import json
import platform
import sys
from pathlib import Path

from aiops_diag.agent.release import verify as verify_agent
from aiops_diag.agent.workflow import validate_isolation
from aiops_diag.data.common import digest, key, save, verified_manifest
from aiops_diag.service.release import verify as verify_service


def _source_hashes(root):
    base = Path(root) / "src" / "aiops_diag"
    return {str(path.relative_to(root)).replace("\\", "/"): digest(path)
            for path in sorted(base.rglob("*.py"))}


def freeze(cfg):
    service = verify_service(cfg["service"])
    agent = verify_agent(cfg["agent"])
    isolation = validate_isolation(cfg["agent"]["paths"]["adev"],
                                   cfg["agent"]["paths"]["atest"])
    value = {
        "schema_version": 1, "product_version": cfg["product_version"],
        "candidate_version": cfg["candidate_version"], "config_hash": cfg["config_hash"],
        "service": {"deployment_release": service["deployment_release"],
                    "release_id": service["release_id"], "manifest_hash": key(service)},
        "components": {"model": "v0.2_lr", "knowledge": "kb_v0.1",
                       "rag": "rag_v0.1", "agent": agent["agent_version"]},
        "agent_release_id": agent["release_id"],
        "agent_candidate_hash": agent["candidate_hash"],
        "evaluation": {
            "adev_hash": digest(cfg["agent"]["paths"]["adev"]),
            "atest_hash": digest(cfg["agent"]["paths"]["atest"]),
            "isolation": isolation,
        },
        "source_hashes": _source_hashes(cfg["root"]),
        "safety_policy": {
            "optional_llm_router_enabled": False,
            "execution_allowed": False,
            "test_tuning_forbidden": True,
        },
    }
    value["candidate_hash"] = key(value)
    directory = Path(cfg["paths"]["release_dir"])
    directory.mkdir(parents=True, exist_ok=True)
    save(directory / "release.json", value)
    save(directory / "manifest.json", {"schema_version": 1,
         "candidate_hash": value["candidate_hash"],
         "artifacts": {"release.json": digest(directory / "release.json")}})
    verified_manifest(directory, "manifest.json")
    return value


def verify(cfg):
    directory = Path(cfg["paths"]["release_dir"])
    manifest = verified_manifest(directory, "manifest.json")
    value = json.loads((directory / "release.json").read_text(encoding="utf-8"))
    if value.get("product_version") != "v1.0" or value.get("config_hash") != cfg["config_hash"]:
        raise ValueError("Product release configuration changed")
    if manifest.get("candidate_hash") != value.get("candidate_hash"):
        raise ValueError("Candidate hash changed")
    current = dict(value)
    candidate_hash = current.pop("candidate_hash")
    if key(current) != candidate_hash:
        raise ValueError("Candidate release contents changed")
    if value.get("source_hashes") != _source_hashes(cfg["root"]):
        raise ValueError("Source code changed after candidate freeze")
    service = verify_service(cfg["service"])
    agent = verify_agent(cfg["agent"])
    if value["service"]["manifest_hash"] != key(service):
        raise ValueError("Service release changed after candidate freeze")
    if value["agent_candidate_hash"] != agent["candidate_hash"]:
        raise ValueError("Agent release changed after candidate freeze")
    for name in ("adev", "atest"):
        if value["evaluation"][f"{name}_hash"] != digest(cfg["agent"]["paths"][name]):
            raise ValueError(f"{name} changed after candidate freeze")
    return value


def _read_optional(path):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def accept(cfg):
    release = verify(cfg)
    work = Path(cfg["paths"]["work_dir"])
    replay = _read_optional(work / "atest_replay_summary.json")
    online = _read_optional(work / "atest_online_summary.json")
    tests = _read_optional(work / "test_acceptance.json")
    environment = _read_optional(work / "environment_acceptance.json")
    containers = _read_optional(work / "container_acceptance.json")
    gates = cfg["gates"]
    checks = {
        "replay_complete": bool(replay and replay["runs"][0]["cases"]
                                == gates["expected_atest_cases"]),
        "online_repeats": bool(online and online["completed_repeats"]
                               == gates["expected_online_repeats"]),
        "task_success": bool(online and online["aggregate"]["task_success_rate"]["mean"]
                             >= gates["minimum_task_success_rate"]),
        "mandatory_review": bool(online and online["aggregate"]["mandatory_review_recall"]["mean"]
                                >= gates["minimum_mandatory_review_recall"]),
        "citations": bool(online and online["aggregate"]["citation_valid_rate"]["mean"]
                          >= gates["minimum_citation_valid_rate"]),
        "no_execution": bool(online and all(run["execution_violations"]
                            <= gates["maximum_execution_violations"] for run in online["runs"])),
        "no_unauthorized_tools": bool(online and all(run["unauthorized_tool_calls"]
                                     <= gates["maximum_unauthorized_tool_calls"]
                                     for run in online["runs"])),
        "no_invalid_references": bool(online and all(run["invalid_references_released"]
                                     <= gates["maximum_invalid_references_released"]
                                     for run in online["runs"])),
        "budget": bool(online and all(not run["stopped_by_budget"]
                       and run["budget_violations"] <= gates["maximum_budget_violations"]
                       for run in online["runs"])),
        "tests": bool(tests and tests.get("passed")),
        "fresh_environment": bool(environment and environment.get("passed")),
        "containers": bool(containers and containers.get("passed")),
    }
    status = "RELEASED" if all(checks.values()) else "CANDIDATE_ONLY"
    result = {
        "schema_version": 1, "product_version": "v1.0", "status": status,
        "candidate_hash": release["candidate_hash"], "checks": checks,
        "atest": {"replay": replay, "online": online},
        "environment": {"tests": tests, "fresh": environment, "containers": containers},
    }
    save(work / "acceptance.json", result)
    return result


def export(cfg):
    result = accept(cfg)
    online = (result["atest"].get("online") or {})
    runs = online.get("runs", [])
    usage = {"input_tokens": sum((run.get("usage_delta") or {}).get("input_tokens", 0)
                                 for run in runs),
             "output_tokens": sum((run.get("usage_delta") or {}).get("output_tokens", 0)
                                  for run in runs),
             "estimated_cost_cny": round(sum(
                 (run.get("usage_delta") or {}).get("estimated_cost_cny", 0) for run in runs), 8)}
    summary = {
        "schema_version": 1, "product_version": result["product_version"],
        "release_status": result["status"], "candidate_hash": result["candidate_hash"],
        "components": {"model": "v0.2_lr", "knowledge": "kb_v0.1",
                       "rag": "rag_v0.1", "agent": "agent_v0.2"},
        "atest": {"cases": 40, "online_repeats": online.get("completed_repeats", 0),
                  "aggregate": online.get("aggregate"), "usage": usage},
        "safety_checks": result["checks"],
        "environment": {"python": sys.version.split()[0], "platform": platform.platform()},
        "limitations": [
            "HDFS_v1没有真实根因标签，结果不表示根因准确率。",
            "DeepSeek可选工具路由因W9开发准确率55%而保持关闭。",
            "单机CPU研究原型不代表生产容量或跨系统泛化。",
        ],
    }
    save(cfg["paths"]["summary"], summary)
    return summary
