"""模块说明：读取、校验并规范化当前模块的 YAML 配置。"""

import json
from pathlib import Path

import yaml

from aiops_diag.data.common import config_root, key, logical_config


# 方法说明：`load` 完成当前步骤的业务处理；参数为 `path`。
def load(path):
    path = Path(path).resolve()
    root = config_root(path)
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    data_path = (root / cfg["data_config"]).resolve()
    data = yaml.safe_load(data_path.read_text(encoding="utf-8"))
    for name in ("raw_dir", "output_dir"):
        data[name] = str((root / data[name]).resolve())
    cfg["root"] = str(root)
    cfg["config_path"] = str(path)
    cfg["data"] = data
    cfg["w1_dir"] = str(Path(data["output_dir"]) / cfg["w1_version"])
    cfg["protocol_dir"] = str(Path(cfg["w1_dir"]) / cfg["protocol_name"])
    cfg["artifact_dir"] = str((root / cfg["paths"]["artifacts_dir"] / cfg["protocol_name"]).resolve())
    cfg["experiment_dir"] = str((root / cfg["paths"]["experiments_dir"] / cfg["protocol_name"]).resolve())
    comparable = {k: v for k, v in cfg.items() if k not in {
        "root", "config_path", "data", "w1_dir", "protocol_dir", "artifact_dir", "experiment_dir"}}
    cfg["config_hash"] = key(logical_config(comparable))
    return cfg


# 方法说明：`resolved` 完成当前步骤的业务处理；参数为 `cfg`。
def resolved(cfg):
    hidden = {"root", "config_path", "data", "w1_dir", "protocol_dir", "artifact_dir", "experiment_dir"}
    return json.loads(json.dumps({k: v for k, v in cfg.items() if k not in hidden}))
