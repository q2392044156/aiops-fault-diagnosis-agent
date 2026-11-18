"""离线检测三轮运行共用的产物约定：run_id 命名、git 提交记录、清单校验与分阶段发布。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from aiops_diag.common import digest, key, save, verified_manifest


def git_commit(root):
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, check=True,
                              capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def run_name(prefix, values):
    return f"{prefix}_" + key(list(values))[:16]


def stage(directory, manifest_name):
    directory = Path(directory)
    verified_manifest(directory, "registry.json")
    return verified_manifest(directory, manifest_name)


def publish(directory, manifest_name, details, filenames):
    directory = Path(directory)
    details = {**details, "artifacts": {name: digest(directory / name) for name in filenames}}
    save(directory / manifest_name, details)
    save(directory / "registry.json", {
        "schema_version": 1, "artifacts": {manifest_name: digest(directory / manifest_name)}})
    return stage(directory, manifest_name)
