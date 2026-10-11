import json
import os
from pathlib import Path

import yaml

from aiops_diag.data.common import key
from aiops_diag.modeling.config import load as load_model_config


def load(path):
    path = Path(path).resolve()
    root = path.parent.parent
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 2:
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

