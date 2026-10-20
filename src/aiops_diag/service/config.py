import json
import os
from pathlib import Path

import yaml

from aiops_diag.data.common import key
from aiops_diag.modeling.config import load as load_model_config
from aiops_diag.retrieval.config import load as load_retrieval_config
from aiops_diag.rag.config import load as load_rag_config
from aiops_diag.agent.config import load as load_agent_config


def load(path):
    path = Path(path).resolve()
    root = path.parent.parent
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") not in (2, 3, 4, 5):
        raise ValueError("Unsupported service configuration schema")
    if raw["server"].get("workers") != 1:
        raise ValueError("The service requires exactly one API process")
    backend = raw.get("agent_backend", "legacy")
    if backend not in ("legacy", "v11_candidate", "framework_candidate"):
        raise ValueError("Unsupported Agent backend")
    if backend in ("v11_candidate", "framework_candidate") and (
            not raw.get("agent_config") or set(raw.get("v11_candidate", {})) != {
                "protocol", "calibration", "release_dir"}):
        raise ValueError("v1.1 candidate requires Agent and sealed candidate paths")
    if backend == "framework_candidate" and set(raw.get("framework_candidate", {})) != {
            "base_service_config", "release_dir", "prior_blind_observation"}:
        raise ValueError("Framework candidate requires base, release and observation paths")
    execution_backend = raw.get("execution_backend", "legacy")
    report_backend = raw.get("report_backend", "legacy")
    retrieval_backend = raw.get("retrieval_backend", "legacy")
    if execution_backend not in ("legacy", "langgraph"):
        raise ValueError("Unsupported execution backend")
    if report_backend not in ("legacy", "langchain"):
        raise ValueError("Unsupported report backend")
    if retrieval_backend not in ("legacy", "langchain"):
        raise ValueError("Unsupported retrieval backend")
    if backend != "framework_candidate" and any(value != "legacy" for value in (
            execution_backend, report_backend, retrieval_backend)):
        raise ValueError("Framework adapters require the framework candidate backend")
    cfg = json.loads(json.dumps(raw))
    cfg["root"] = str(root)
    cfg["config_path"] = str(path)
    cfg["model"] = load_model_config(root / raw["model_config"])
    if raw.get("retrieval_config"):
        cfg["retrieval"] = load_retrieval_config(root / raw["retrieval_config"])
    if raw.get("rag_config"):
        cfg["rag"] = load_rag_config(root / raw["rag_config"])
    if raw.get("agent_config"):
        cfg["agent"] = load_agent_config(root / raw["agent_config"])
    if backend in ("v11_candidate", "framework_candidate"):
        cfg["v11_candidate"] = {name: str((root / value).resolve())
                                for name, value in raw["v11_candidate"].items()}
        for name, env_name in (("calibration", "AIOPS_V11_CALIBRATION"),
                               ("release_dir", "AIOPS_V11_AGENT_RELEASE_DIR")):
            if os.environ.get(env_name):
                cfg["v11_candidate"][name] = str(Path(os.environ[env_name]).resolve())
    if backend == "framework_candidate":
        cfg["framework_candidate"] = {name: str((root / value).resolve())
                                      for name, value in raw["framework_candidate"].items()}
        if os.environ.get("AIOPS_FRAMEWORK_RELEASE_DIR"):
            cfg["framework_candidate"]["release_dir"] = str(
                Path(os.environ["AIOPS_FRAMEWORK_RELEASE_DIR"]).resolve())
    if backend in ("v11_candidate", "framework_candidate"):
        query_builder_path = raw.get("query_builder_config")
        if not query_builder_path:
            raise ValueError("Candidate service requires query_builder_config")
        cfg["query_builder_config"] = str((root / query_builder_path).resolve())
    for field in ("w4_release_dir", "release_dir"):
        cfg[field] = str((root / raw[field]).resolve())
    for field in ("runtime_dir", "database"):
        cfg["paths"][field] = str((root / raw["paths"][field]).resolve())
    registered = {}
    for name, item in raw.get("registered_batches", {}).items():
        registered[name] = {**item, "path": str((root / item["path"]).resolve())}
    cfg["registered_batches"] = registered
    if os.environ.get("AIOPS_RELEASE_DIR"):
        cfg["release_dir"] = str(Path(os.environ["AIOPS_RELEASE_DIR"]).resolve())
    if os.environ.get("AIOPS_HOST"):
        cfg["server"]["host"] = os.environ["AIOPS_HOST"]
    if os.environ.get("AIOPS_RUNTIME_DIR"):
        runtime = Path(os.environ["AIOPS_RUNTIME_DIR"]).resolve()
        cfg["paths"]["runtime_dir"] = str(runtime)
        cfg["paths"]["database"] = str(runtime / "service.sqlite3")
    if os.environ.get("AIOPS_REGISTERED_ROOT"):
        data_root = Path(os.environ["AIOPS_REGISTERED_ROOT"]).resolve()
        for item in cfg["registered_batches"].values():
            item["path"] = str(data_root / Path(item["path"]).name)
    comparable = json.loads(json.dumps(raw))
    cfg["config_hash"] = key(comparable)
    cfg["processing_hash"] = key({
        "schema_version": raw["schema_version"],
        "processing": raw["processing"],
        "model_config": raw["model_config"],
    })
    return cfg

