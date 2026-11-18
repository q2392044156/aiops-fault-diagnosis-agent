"""读取诊断配置：预算上限、工具开关与代理后端选择。"""

import json
import os
from pathlib import Path

import yaml

from aiops_diag.common import config_root, key, logical_config
from online.knowledge.generation.settings import load as load_rag_config


def load(path):
    path = Path(path).resolve()
    root = config_root(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1:
        raise ValueError("Unsupported agent configuration schema")
    required = {"max_tool_calls": 8, "max_llm_calls": 3, "max_tokens": 12000,
                "max_revision": 2, "max_active_seconds": 120}
    for name, expected in required.items():
        if int(raw["workflow"].get(name, -1)) != expected:
            raise ValueError(f"Agent workflow requires {name}={expected}")
    cfg = json.loads(json.dumps(raw))
    cfg["root"] = str(root)
    cfg["config_path"] = str(path)
    cfg["service_config_path"] = str((root / raw["service_config"]).resolve())
    cfg["rag"] = load_rag_config(root / raw["rag_config"])
    for name, value in raw["paths"].items():
        cfg["paths"][name] = str((root / value).resolve())
    if os.environ.get("AIOPS_AGENT_RELEASE_DIR"):
        cfg["paths"]["release_dir"] = str(Path(
            os.environ["AIOPS_AGENT_RELEASE_DIR"]).resolve())
    registry_env = raw["approval"]["reviewer_registry_env"]
    cfg["approval"]["reviewer_registry"] = os.environ.get(registry_env)
    cfg["config_hash"] = key(logical_config(raw))
    return cfg
