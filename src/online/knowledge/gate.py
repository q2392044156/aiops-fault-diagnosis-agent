"""在冻结知识库之上做证据门控：按首条证据的稠密相似度决定是否返回，并用开发与校准切分校准阈值。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiops_diag.common import digest, save
from online.knowledge.evaluation import choose_gate, evaluate

if TYPE_CHECKING:
    from online.knowledge.release import FrozenRetriever


class GatedRetriever:
    """只对已返回的首条证据做门控，不换用另一条凑数文档。"""

    def __init__(self, frozen: FrozenRetriever, threshold: float) -> None:
        self.frozen = frozen
        self.manifest = frozen.manifest
        self.threshold = float(threshold)
        if not -1.0 <= self.threshold <= 1.0:
            raise ValueError("Dense similarity threshold must be in [-1, 1]")

    def verify_integrity(self) -> bool:
        return self.frozen.verify_integrity()

    def public(self) -> dict[str, Any]:
        return {**self.frozen.public(), "gate_threshold": self.threshold}

    def chunk(self, chunk_id: str) -> dict[str, Any] | None:
        return self.frozen.chunk(chunk_id)

    def search(self, query: str, mode: str | None = None, top_k: int | None = None,
               component: str | None = None, product_version: str | None = None,
               apply_gate: bool = True) -> dict[str, Any]:
        result = self.frozen.search(query, mode=mode, top_k=top_k, component=component,
                                    product_version=product_version, apply_gate=False)
        items = result["items"]
        score = items[0].get("dense_score") if items else None
        result = {**result, "gate_score": score,
                  "gate_strategy": "top_result_dense_v11"}
        if apply_gate and (score is None or score < self.threshold):
            result["status"] = "insufficient_evidence"
            result["items"] = []
        return result


def calibrate(frozen: FrozenRetriever, protocol_path: str | Path,
              maximum_false_rate: float = 0.10) -> dict[str, Any]:
    """只用开发与校准切分选阈值；独立测试集在冻结之后才打开。"""
    protocol_path = Path(protocol_path)
    directory = protocol_path.resolve().parent
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    if protocol.get("schema_version") != 2:
        raise ValueError("Expected v1.1 protocol")
    splits = {}
    for name in ("development", "calibration"):
        entry = protocol["splits"][name]
        paths = {field: (directory / entry[field]).resolve()
                 for field in ("queries", "qrels")}
        for field, path in paths.items():
            if not path.is_relative_to(directory) or digest(path) != entry[f"{field}_sha256"]:
                raise ValueError(f"Sealed {name} {field} changed")
        splits[name] = {field: [json.loads(line) for line in path.read_text(
            encoding="utf-8").splitlines() if line.strip()]
                        for field, path in paths.items()}
    queries = [*splits["development"]["queries"], *splits["calibration"]["queries"]]
    gate = GatedRetriever(frozen, 0.0)
    threshold = choose_gate(gate, queries, maximum_false_rate)
    gate.threshold = threshold
    mode, top_k = frozen.manifest["default_mode"], frozen.manifest["default_k"]
    metrics = {name: evaluate(gate, rows["queries"], rows["qrels"], mode,
                              top_k, apply_gate=True)["metrics"]
               for name, rows in splits.items()}
    return {"schema_version": 1, "status": "calibration_only",
            "protocol_sha256": digest(protocol_path),
            "kb_release_id": frozen.manifest["kb_release_id"],
            "gate_strategy": "top_result_dense_v11", "gate_threshold": threshold,
            "maximum_false_rate_target": maximum_false_rate, "metrics": metrics}


if __name__ == "__main__":
    import argparse

    from online.knowledge.release import FrozenRetriever
    from online.knowledge.settings import load

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("retrieval_config", type=Path)
    parser.add_argument("protocol", type=Path)
    parser.add_argument("output", type=Path)
    options = parser.parse_args()
    result = calibrate(FrozenRetriever(load(options.retrieval_config)),
                       options.protocol)
    save(options.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
