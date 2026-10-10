import json
from pathlib import Path

import yaml

from aiops_diag.data.common import key
from aiops_diag.modeling.config import load as load_w2
from aiops_diag.modeling.lstm_config import load_lstm


def load(path):
    path = Path(path).resolve()
    root = path.parent.parent
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
    value["config_hash"] = key(comparable)
    return value


def resolved(cfg):
    hidden = {"root", "config_path", "w2", "lstm", "artifact_dir", "experiment_dir"}
    return json.loads(json.dumps({name: value for name, value in cfg.items()
                                  if name not in hidden}))
