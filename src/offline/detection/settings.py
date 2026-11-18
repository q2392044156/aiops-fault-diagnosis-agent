"""读取 W2 / LSTM / selection 三套检测配置，补齐派生路径并计算 config_hash。"""

import json
from pathlib import Path

import yaml

from aiops_diag.common import config_root, key, logical_config

DERIVED = ("root", "config_path", "data", "w2", "lstm", "w1_dir", "protocol_dir",
           "artifact_dir", "experiment_dir", "w2_artifact_dir", "feature_dir",
           "experiment_root")


def _yaml(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _base(path):
    """读主配置与数据集配置，回填绝对路径和 w1 目录。"""
    path = Path(path).resolve()
    root = config_root(path)
    cfg = _yaml(path)
    cfg["root"] = str(root)
    cfg["config_path"] = str(path)
    cfg["data"] = _yaml(root / cfg["data_config"])
    for name in ("raw_dir", "output_dir"):
        cfg["data"][name] = str((root / cfg["data"][name]).resolve())
    cfg["w1_dir"] = str(Path(cfg["data"]["output_dir"]) / cfg["w1_version"])
    cfg["protocol_dir"] = str(Path(cfg["w1_dir"]) / cfg["protocol_name"])
    return cfg, root


def _seal(cfg):
    """配置哈希只覆盖可比较字段：运行期路径与派生目录不参与。"""
    cfg["config_hash"] = key(logical_config({k: value for k, value in cfg.items()
                                             if k not in DERIVED}))
    return cfg


def resolved(cfg):
    """去掉运行期字段后的配置副本，用于落盘与哈希复核。"""
    return json.loads(json.dumps({k: value for k, value in cfg.items()
                                  if k not in DERIVED}))


def load(path):
    """W2 特征与规则模型训练配置。"""
    cfg, root = _base(path)
    cfg["artifact_dir"] = str((root / cfg["paths"]["artifacts_dir"] /
                               cfg["protocol_name"]).resolve())
    cfg["experiment_dir"] = str((root / cfg["paths"]["experiments_dir"] /
                                 cfg["protocol_name"]).resolve())
    return _seal(cfg)


def load_lstm(path):
    """LSTM 训练配置：在 W2 字段之外多读一份 w2 段与序列特征目录。"""
    cfg, root = _base(path)
    cfg["w2"] = _yaml(root / cfg["w2_config"])
    cfg["w2_artifact_dir"] = str((root / cfg["w2"]["paths"]["artifacts_dir"] /
                                  cfg["protocol_name"]).resolve())
    cfg["feature_dir"] = str((root / cfg["paths"]["artifacts_dir"] /
                              cfg["protocol_name"] / cfg["feature_version"]).resolve())
    cfg["experiment_root"] = str((root / cfg["paths"]["experiments_dir"] /
                                  cfg["protocol_name"]).resolve())
    return _seal(cfg)


def load_selection(path):
    """选择实验配置：组合 W2 与 LSTM 两份上游配置，产物落在各自协议目录下。"""
    path = Path(path).resolve()
    root = config_root(path)
    cfg = _yaml(path)
    cfg["root"] = str(root)
    cfg["config_path"] = str(path)
    cfg["w2"] = load(root / cfg["w2_config"])
    cfg["lstm"] = load_lstm(root / cfg["lstm_config"])
    cfg["artifact_dir"] = str((root / cfg["paths"]["artifacts_dir"] /
                               cfg["w2"]["protocol_name"] / cfg["protocol_name"]).resolve())
    cfg["experiment_dir"] = str((root / cfg["paths"]["experiments_dir"] /
                                 cfg["w2"]["protocol_name"] / cfg["protocol_name"]).resolve())
    return _seal(cfg)
