import json
from pathlib import Path

import yaml

from aiops_diag.agent.config import load as load_agent
from aiops_diag.data.common import key
from aiops_diag.service.config import load as load_service


def load(path):
    path = Path(path).resolve()
    root = path.parent.parent
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1 or raw.get("product_version") != "v1.0":
        raise ValueError("Unsupported product release configuration")
    cfg = json.loads(json.dumps(raw))
    cfg["root"] = str(root)
    cfg["config_path"] = str(path)
    cfg["service"] = load_service(root / raw["service_config"])
    cfg["agent"] = load_agent(root / raw["agent_config"])
    for name, value in raw["paths"].items():
        cfg["paths"][name] = str((root / value).resolve())
    cfg["config_hash"] = key(raw)
    return cfg
