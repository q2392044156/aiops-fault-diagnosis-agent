"""模块说明：校验并生成当前模块的不可变发布清单。"""

import json
from pathlib import Path

from aiops_diag.common import digest, key, verified_manifest


# 方法说明：`verify` 完成当前步骤的业务处理；参数为 `cfg`。
def verify(cfg):
    from .engine import SYSTEM_PROMPT
    directory = Path(cfg["paths"]["release_dir"])
    registry = verified_manifest(directory, "registry.json")
    manifest = json.loads((directory / "rag_release.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("rag_version") != cfg["rag_version"]:
        raise ValueError("Unexpected RAG release")
    if registry.get("release_hash") != key(manifest):
        raise ValueError("RAG release hash changed")
    if manifest["config_hash"] != cfg["config_hash"]:
        raise ValueError("RAG configuration changed after publishing")
    if manifest.get("prompt_hash") != key(SYSTEM_PROMPT):
        raise ValueError("RAG prompt changed after publishing")
    kb = cfg["retrieval"]
    kb_manifest = json.loads((Path(kb["paths"]["release_dir"]) / "retrieval_release.json")
                             .read_text(encoding="utf-8"))
    if manifest["kb_release_id"] != kb_manifest["kb_release_id"]:
        raise ValueError("Knowledge release changed after publishing RAG")
    return manifest


# 方法说明：`public` 完成当前步骤的业务处理；参数为 `cfg`。
def public(cfg):
    manifest = verify(cfg)
    return {name: manifest[name] for name in (
        "schema_version", "rag_version", "kb_release_id", "provider", "model",
        "prompt_version", "prompt_hash", "config_hash", "reranker_enabled")}
