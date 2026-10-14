import json
import os
from pathlib import Path

import yaml

from aiops_diag.data.common import key
from aiops_diag.retrieval.config import load as load_retrieval_config


def load(path):
    path = Path(path).resolve()
    root = path.parent.parent
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1:
        raise ValueError("Unsupported RAG configuration schema")
    if raw["provider"]["base_url"].rstrip("/") != "https://api.deepseek.com":
        raise ValueError("W8 only permits the official DeepSeek API endpoint")
    if raw["provider"]["model"] != "deepseek-flash":
        raise ValueError("W8 requires the frozen deepseek-flash model identifier")
    cfg = json.loads(json.dumps(raw))
    cfg["root"] = str(root)
    cfg["config_path"] = str(path)
    cfg["retrieval"] = load_retrieval_config(root / raw["retrieval_config"])
    for name, value in raw["paths"].items():
        cfg["paths"][name] = str((root / value).resolve())
    release_override = os.environ.get("AIOPS_RAG_RELEASE_DIR")
    if release_override:
        cfg["paths"]["release_dir"] = str(Path(release_override).resolve())
    ledger_override = os.environ.get("AIOPS_RAG_BUDGET_LEDGER")
    if ledger_override:
        cfg["paths"]["budget_ledger"] = str(Path(ledger_override).resolve())
    cfg["config_hash"] = key(raw)
    return cfg
