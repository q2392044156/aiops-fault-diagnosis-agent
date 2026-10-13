import math
import statistics
import time
from collections import defaultdict

import numpy as np

from .engine import tokenize


def validate_queries(queries, qrels, split):
    if len(queries) != 60:
        raise ValueError(f"R{split} must contain exactly 60 queries")
    if sum(item["has_answer"] for item in queries) != 40:
        raise ValueError(f"R{split} must contain exactly 40 answerable queries")
    if sum(not item["has_answer"] for item in queries) != 20:
        raise ValueError(f"R{split} must contain exactly 20 no-answer queries")
    ids = {item["query_id"] for item in queries}
    if len(ids) != 60 or any(item["split"] != split for item in queries):
        raise ValueError(f"R{split} query identity or split is invalid")
    answer_ids = {item["query_id"] for item in queries if item["has_answer"]}
    if not qrels or any(row["query_id"] not in answer_ids for row in qrels):
        raise ValueError(f"R{split} qrels must refer only to answerable queries")
    if answer_ids - {row["query_id"] for row in qrels}:
        raise ValueError(f"R{split} answerable query is missing qrels")


def _percentile(values, q):
    return float(np.percentile(np.asarray(values, dtype=np.float64), q)) if values else 0.0


def evaluate(engine, queries, qrels, mode, top_k, apply_gate=False):
    relevance = defaultdict(dict)
    for row in qrels:
        relevance[row["query_id"]][row["evidence_unit_id"]] = int(row["relevance"])
    rows, latencies = [], []
    for query in queries:
        started = time.perf_counter()
        result = engine.search(query["query"], mode=mode, top_k=top_k,
                               component=query.get("component"),
                               product_version=query.get("product_version"),
                               apply_gate=apply_gate)
        elapsed = (time.perf_counter() - started) * 1000
        latencies.append(elapsed)
        grades, found_units = [], set()
        for item in result["items"]:
            values = [relevance[query["query_id"]].get(unit, 0)
                      for unit in item["evidence_unit_ids"]]
            grades.append(max(values, default=0))
            found_units.update(unit for unit in item["evidence_unit_ids"]
                               if relevance[query["query_id"]].get(unit, 0) > 0)
        expected = {unit for unit, value in relevance[query["query_id"]].items() if value > 0}
        recall = len(found_units) / len(expected) if expected else None
        first = next((index for index, value in enumerate(grades, 1) if value > 0), None)
        mrr = 1.0 / first if first else (0.0 if expected else None)
        dcg = sum((2 ** grade - 1) / math.log2(index + 1)
                  for index, grade in enumerate(grades, 1))
        ideal = sorted(relevance[query["query_id"]].values(), reverse=True)[:top_k]
        idcg = sum((2 ** grade - 1) / math.log2(index + 1)
                   for index, grade in enumerate(ideal, 1))
        ndcg = dcg / idcg if idcg else None
        rows.append({"query_id": query["query_id"], "family_id": query["family_id"],
                     "has_answer": query["has_answer"], "status": result["status"],
                     "recall": recall, "mrr": mrr, "ndcg": ndcg,
                     "gate_score": result["gate_score"], "latency_ms": elapsed,
                     "context_tokens": sum(len(tokenize(item["text"]))
                                           for item in result["items"]),
                     "chunk_ids": [item["chunk_id"] for item in result["items"]]})
    answers = [row for row in rows if row["has_answer"]]
    noanswers = [row for row in rows if not row["has_answer"]]
    metrics = {
        "mode": mode, "top_k": top_k, "query_count": len(rows),
        "recall": statistics.fmean(row["recall"] for row in answers),
        "mrr": statistics.fmean(row["mrr"] for row in answers),
        "ndcg": statistics.fmean(row["ndcg"] for row in answers),
        "p50_ms": _percentile(latencies, 50), "p95_ms": _percentile(latencies, 95),
        "mean_context_tokens": statistics.fmean(row["context_tokens"] for row in rows),
    }
    if apply_gate:
        metrics.update({
            "answer_coverage": sum(row["status"] == "evidence_found" for row in answers) / len(answers),
            "answer_false_refusal": sum(row["status"] != "evidence_found" for row in answers) / len(answers),
            "no_answer_refusal": sum(row["status"] != "evidence_found" for row in noanswers) / len(noanswers),
            "no_answer_false_return": sum(row["status"] == "evidence_found" for row in noanswers) / len(noanswers),
        })
    return {"metrics": metrics, "queries": rows}


def choose_gate(engine, queries, maximum_false_rate):
    scored = []
    for query in queries:
        result = engine.search(query["query"], mode="hybrid", top_k=5,
                               component=query.get("component"), apply_gate=False)
        scored.append((query["has_answer"], float(result["gate_score"])))
    candidates = sorted({score for _, score in scored} |
                        {max(score for _, score in scored) + 1e-9})
    feasible = []
    for threshold in candidates:
        answer = [score >= threshold for expected, score in scored if expected]
        noanswer = [score >= threshold for expected, score in scored if not expected]
        false_rate = sum(noanswer) / len(noanswer)
        if false_rate <= maximum_false_rate:
            feasible.append((sum(answer) / len(answer), -false_rate, threshold))
    if not feasible:
        raise ValueError("No evidence gate satisfies the no-answer constraint")
    return max(feasible)[2]
