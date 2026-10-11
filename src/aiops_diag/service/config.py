import json
from pathlib import Path

import yaml

from aiops_diag.data.common import key
from aiops_diag.modeling.config import load as load_model_config


def load(path):
    path = Path(path).resolve()
    root = path.parent.parent
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1:
        raise ValueError("Unsupported service configuration schema")
    if raw["server"].get("workers") != 1:
        raise ValueError("W5 requires exactly one service worker")
    cfg = json.loads(json.dumps(raw))
    cfg["root"] = str(root)
    cfg["config_path"] = str(path)
    cfg["model"] = load_model_config(root / raw["model_config"])
    for field in ("w4_release_dir", "release_dir"):
        cfg[field] = str((root / raw[field]).resolve())
    for field in ("runtime_dir", "database"):
        cfg["paths"][field] = str((root / raw["paths"][field]).resolve())
    registered = {}
    for name, item in raw.get("registered_batches", {}).items():
        registered[name] = {**item, "path": str((root / item["path"]).resolve())}
    cfg["registered_batches"] = registered
    comparable = json.loads(json.dumps(raw))
    cfg["config_hash"] = key(comparable)
    cfg["processing_hash"] = key({
        "schema_version": raw["schema_version"],
        "processing": raw["processing"],
        "model_config": raw["model_config"],
    })
    return cfg

