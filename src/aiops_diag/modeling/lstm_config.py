import json
from pathlib import Path

import yaml

from aiops_diag.data.common import key


def load_lstm(path):
    path = Path(path).resolve()
    root = path.parent.parent
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    data_path = (root / cfg["data_config"]).resolve()
    w2_path = (root / cfg["w2_config"]).resolve()
    data = yaml.safe_load(data_path.read_text(encoding="utf-8"))
    w2 = yaml.safe_load(w2_path.read_text(encoding="utf-8"))
    for name in ("raw_dir", "output_dir"):
        data[name] = str((root / data[name]).resolve())
    cfg["root"] = str(root)
    cfg["config_path"] = str(path)
    cfg["data"] = data
    cfg["w2"] = w2
    cfg["w1_dir"] = str(Path(data["output_dir"]) / cfg["w1_version"])
    cfg["protocol_dir"] = str(Path(cfg["w1_dir"]) / cfg["protocol_name"])
    cfg["w2_artifact_dir"] = str((root / w2["paths"]["artifacts_dir"] /
                                  cfg["protocol_name"]).resolve())
    cfg["feature_dir"] = str((root / cfg["paths"]["artifacts_dir"] /
                              cfg["protocol_name"] / cfg["feature_version"]).resolve())
    cfg["experiment_root"] = str((root / cfg["paths"]["experiments_dir"] /
                                  cfg["protocol_name"]).resolve())
    hidden = {"root", "config_path", "data", "w2", "w1_dir", "protocol_dir",
              "w2_artifact_dir", "feature_dir", "experiment_root"}
    cfg["config_hash"] = key({k: v for k, v in cfg.items() if k not in hidden})
    return cfg


def resolved_lstm(cfg):
    hidden = {"root", "config_path", "data", "w2", "w1_dir", "protocol_dir",
              "w2_artifact_dir", "feature_dir", "experiment_root"}
    return json.loads(json.dumps({k: v for k, v in cfg.items() if k not in hidden}))
