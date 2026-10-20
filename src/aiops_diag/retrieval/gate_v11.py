"""Opt-in v1.1 evidence gate over an unchanged frozen knowledge release."""

import json
from pathlib import Path

from aiops_diag.data.common import digest, save

from .evaluation import evaluate


def choose_gate_candidate(engine, queries, maximum_false_rate):
    """Choose a threshold with the same component and version filters as serving."""
    scores = []
    for query in queries:
        result = engine.search(query["query"], mode="hybrid", top_k=5,
                               component=query.get("component"),
                               product_version=query.get("product_version"),
                               apply_gate=False)
        scores.append((query["has_answer"], result["gate_score"]))
    if not any(answer for answer, _ in scores) or all(answer for answer, _ in scores):
        raise ValueError("Calibration requires answerable and no-answer queries")
    candidates = sorted({score for _, score in scores if score is not None})
    if not candidates:
        raise ValueError("Calibration has no eligible evidence scores")
    candidates.append(max(candidates) + 1e-9)
    feasible = []
    for threshold in candidates:
        answers = [score is not None and score >= threshold for expected, score in scores
                   if expected]
        noanswers = [score is not None and score >= threshold for expected, score in scores
                     if not expected]
        false_rate = sum(noanswers) / len(noanswers)
        if false_rate <= maximum_false_rate:
            feasible.append((sum(answers) / len(answers), -false_rate, threshold))
    return max(feasible)[2]


class CandidateRetriever:
    """Gate the returned top evidence, not a different eligible document."""

    def __init__(self, frozen, threshold):
        self.frozen = frozen
        self.manifest = frozen.manifest
        self.threshold = float(threshold)
        if not -1.0 <= self.threshold <= 1.0:
            raise ValueError("Dense similarity threshold must be in [-1, 1]")

    def verify_integrity(self):
        return self.frozen.verify_integrity()

    def public(self):
        return {**self.frozen.public(), "gate_threshold": self.threshold}

    def chunk(self, chunk_id):
        return self.frozen.chunk(chunk_id)

    def search(self, query, mode=None, top_k=None, component=None, product_version=None,
               apply_gate=True):
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


def calibrate_candidate(frozen, protocol_path, maximum_false_rate=0.10):
    """Tune using development and calibration only; never open the test files."""
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
    gate = CandidateRetriever(frozen, 0.0)
    threshold = choose_gate_candidate(gate, queries, maximum_false_rate)
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

    from .config import load
    from .release import FrozenRetriever

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("retrieval_config", type=Path)
    parser.add_argument("protocol", type=Path)
    parser.add_argument("output", type=Path)
    options = parser.parse_args()
    result = calibrate_candidate(FrozenRetriever(load(options.retrieval_config)),
                                 options.protocol)
    save(options.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
