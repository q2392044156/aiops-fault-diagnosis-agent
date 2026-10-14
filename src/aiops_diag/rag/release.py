import json
from pathlib import Path

from aiops_diag.data.common import digest, key, verified_manifest


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


def public(cfg):
    manifest = verify(cfg)
    return {name: manifest[name] for name in (
        "schema_version", "rag_version", "kb_release_id", "provider", "model",
        "prompt_version", "prompt_hash", "config_hash", "reranker_enabled")}
