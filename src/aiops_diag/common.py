"""
通用工具函数
包括哈希计算、 JSON 序列化、配置文件解析等

"""
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import yaml


# 计算文件的哈希值, 默认使用 SHA-256 算法
def digest(path: str | Path, algorithm: str = "sha256") -> str:
    h = hashlib.new(algorithm)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

# 将 Python 对象保存为 JSON 文件, 并确保目录存在
def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

# 计算 Python 对象的哈希值, 默认使用 SHA-256 算法
def key(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()

# 根据配置文件的新旧目录位置确定仓库根目录，兼容发布制品中的复制配置。
def config_root(path: str | Path) -> Path:
    path = Path(path).resolve()
    if path.parent.name == "configs" and path.parent.parent.name == "resources":
        return path.parents[2]
    return path.parent.parent

# 将重构后的资源路径还原为稳定逻辑路径，使目录搬迁不会改变业务配置身份。
def logical_config(value: Any) -> Any:
    if isinstance(value, dict):
        return {name: logical_config(item) for name, item in value.items()}
    if isinstance(value, list):
        return [logical_config(item) for item in value]
    if isinstance(value, str):
        for current, logical in (
                ("resources/configs/", "configs/"),
                ("resources/evaluation/", "evaluation/"),
                ("resources/knowledge/", "knowledge/")):
            if value.startswith(current):
                return logical + value[len(current):]
    return value

# 将 Python 对象保存为 JSON 文件, 并确保目录存在
def save(path: str | Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)

# 读取配置文件, 并将相对路径转换为绝对路径
def config(path: str | Path) -> dict[str, Any]:
    path = Path(path).resolve()
    c = yaml.safe_load(path.read_text(encoding="utf-8"))
    root = config_root(path)
    for name in ("raw_dir", "output_dir"):
        c[name] = str((root / c[name]).resolve())
    return c

# 验证清单文件的完整性, 确保所有工件的哈希值与预期一致
def verified_manifest(directory: str | Path, name: str) -> dict[str, Any]:
    directory = Path(directory)
    m = json.loads((directory / name).read_text(encoding="utf-8"))
    for filename, expected in m["artifacts"].items():
        if digest(directory / filename) != expected:
            raise ValueError(f"Artifact changed: {filename}")
    return m

# 按 glob 收集源码清单；任何一个模式匹配不到文件就报错，避免清单在重构后悄悄过期
def source_files(root: str | Path, *patterns: str) -> list[Path]:
    root = Path(root)
    files = set()
    for pattern in patterns:
        matched = [path for path in root.glob(pattern) if path.is_file()]
        if not matched:
            raise ValueError(f"源码清单模式没有匹配到文件: {pattern}")
        files.update(matched)
    return sorted(files)

# 计算分位数，空序列返回 0.0；numpy 延迟导入，让本模块在无科学计算栈时也能加载
def percentile(values: Sequence[float], q: float) -> float:
    import numpy as np
    if not values:
        return 0.0
    return float(np.percentile(np.asarray(values, dtype=np.float64), q))
