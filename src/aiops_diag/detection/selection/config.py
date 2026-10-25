"""模块说明：读取、校验并规范化当前模块的 YAML 配置。"""

import json
from pathlib import Path

import yaml

from aiops_diag.data.common import config_root, key, logical_config
from aiops_diag.detection.config import load as load_w2
from aiops_diag.detection.lstm_config import load_lstm


# 方法说明：`load` 完成当前步骤的业务处理；参数为 `path`。
def load(path):
    path = Path(path).resolve()
    root = config_root(path)
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    w2 = load_w2(root / value["w2_config"])
    lstm = load_lstm(root / value["lstm_config"])
    comparable = dict(value)
    value["root"] = str(root)
    value["config_path"] = str(path)
    value["w2"] = w2
    value["lstm"] = lstm
    value["artifact_dir"] = str((root / value["paths"]["artifacts_dir"] /
                                  w2["protocol_name"] / value["protocol_name"]).resolve())
    value["experiment_dir"] = str((root / value["paths"]["experiments_dir"] /
                                    w2["protocol_name"] / value["protocol_name"]).resolve())
    value["config_hash"] = key(logical_config(comparable))
    return value


# 方法说明：`resolved` 完成当前步骤的业务处理；参数为 `cfg`。
def resolved(cfg):
    hidden = {"root", "config_path", "w2", "lstm", "artifact_dir", "experiment_dir"}
    return json.loads(json.dumps({name: value for name, value in cfg.items()
                                  if name not in hidden}))
