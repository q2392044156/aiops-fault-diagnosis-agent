"""模块说明：读取、校验并规范化当前模块的 YAML 配置。"""

import json
import os
from pathlib import Path

import yaml

from aiops_diag.data.common import config_root, key, logical_config


# 方法说明：`load` 完成当前步骤的业务处理；参数为 `path`。
def load(path):
    path = Path(path).resolve()
    root = config_root(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1:
        raise ValueError("Unsupported retrieval configuration schema")
    cfg = json.loads(json.dumps(raw))
    cfg["root"] = str(root)
    cfg["config_path"] = str(path)
    for name, value in raw["paths"].items():
        cfg["paths"][name] = str((root / value).resolve())
    override = os.environ.get("AIOPS_KB_RELEASE_DIR")
    if override:
        cfg["paths"]["release_dir"] = str(Path(override).resolve())
    comparable = json.loads(json.dumps(raw))
    # These hashes are filled after a deterministic publish and form the service trust anchor.
    # They must not alter the experiment/input hash that produced the release itself.
    comparable.pop("release_integrity", None)
    cfg["config_hash"] = key(logical_config(comparable))
    return cfg
