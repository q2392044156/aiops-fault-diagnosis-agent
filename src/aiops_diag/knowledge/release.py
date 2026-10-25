"""模块说明：校验并生成当前模块的不可变发布清单。"""

import json
from pathlib import Path

import numpy as np

from aiops_diag.data.common import digest, verified_manifest

from .corpus import read_jsonl
from .dense import OnnxEncoder
from .engine import BM25, Retriever


# 方法说明：`verify` 完成当前步骤的业务处理；参数为 `cfg`。
def verify(cfg):
    directory = Path(cfg["paths"]["release_dir"]).resolve()
    integrity = cfg.get("release_integrity", {})
    pinned = {"registry.json": integrity.get("registry_sha256"),
              "retrieval_release.json": integrity.get("manifest_sha256")}
    for name, expected in pinned.items():
        if expected and digest(directory / name) != expected:
            raise ValueError(f"Pinned knowledge release file changed: {name}")
    registry = verified_manifest(directory, "registry.json")
    release = json.loads((directory / "retrieval_release.json").read_text(encoding="utf-8"))
    if release.get("schema_version") != 1 or release.get("kb_release_id") != cfg["kb_version"]:
        raise ValueError("Unexpected knowledge release")
    for relative, expected in registry["artifacts"].items():
        path = (directory / relative).resolve()
        if directory not in path.parents or digest(path) != expected:
            raise ValueError(f"Knowledge artifact changed: {relative}")
    return release


# 类说明：`FrozenRetriever` 封装本模块内聚的数据和行为。
class FrozenRetriever:
    # 方法说明：`__init__` 完成当前步骤的业务处理；参数为 `cfg`。
    def __init__(self, cfg):
        self.cfg = cfg
        self.directory = Path(cfg["paths"]["release_dir"]).resolve()
        self.manifest = verify(cfg)
        chunks = read_jsonl(self.directory / self.manifest["components"]["chunks"])
        bm25_data = json.loads((self.directory / self.manifest["components"]["bm25"])
                                .read_text(encoding="utf-8"))
        bm25 = BM25(bm25_data["tokens"], bm25_data["k1"], bm25_data["b"])
        embeddings = np.load(self.directory / self.manifest["components"]["dense"],
                             allow_pickle=False)
        model_dir = self.directory / self.manifest["components"]["model_dir"]
        encoder = OnnxEncoder(model_dir, self.manifest["query_prefix"],
                              self.manifest["max_length"], self.manifest["batch_size"])
        self.engine = Retriever(chunks, bm25, embeddings, encoder,
                                self.manifest["candidate_k"], self.manifest["rrf_constant"],
                                self.manifest["default_mode"], self.manifest["default_k"],
                                self.manifest["gate_threshold"])
        self._stats = self._artifact_stats()

    # 方法说明：`_artifact_stats` 完成当前步骤的业务处理；参数为 无显式业务参数。
    def _artifact_stats(self):
        registry = json.loads((self.directory / "registry.json").read_text(encoding="utf-8"))
        return {relative: (path.stat().st_size, path.stat().st_mtime_ns)
                for relative in registry["artifacts"]
                for path in (self.directory / relative,)}

    # 方法说明：`verify_integrity` 完成当前步骤的业务处理；参数为 无显式业务参数。
    def verify_integrity(self):
        """Rehash only when a registered file's size or mtime has changed."""
        current = self._artifact_stats()
        if current != self._stats:
            manifest = verify(self.cfg)
            if manifest != self.manifest:
                raise ValueError("Knowledge release manifest changed after loading")
            self._stats = current
        return True

    # 方法说明：`public` 完成当前步骤的业务处理；参数为 无显式业务参数。
    def public(self):
        return {name: self.manifest[name] for name in (
            "schema_version", "kb_release_id", "corpus_hash", "index_hash",
            "model_revision", "model_hash", "default_mode", "default_k",
            "gate_threshold", "chunk_variant", "chunk_count")}

    # 方法说明：`search` 完成当前步骤的业务处理；参数为 `*args`、`**kwargs`。
    def search(self, *args, **kwargs):
        return self.engine.search(*args, **kwargs)

    # 方法说明：`chunk` 完成当前步骤的业务处理；参数为 `chunk_id`。
    def chunk(self, chunk_id):
        return self.engine.by_id.get(chunk_id)
