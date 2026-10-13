import math
import re
import unicodedata
from collections import Counter

import jieba
import numpy as np


TOKEN = re.compile(r"[a-z0-9_.:/-]+|[\u4e00-\u9fff]+", re.I)


def tokenize(text):
    value = unicodedata.normalize("NFKC", text).lower()
    result = []
    for match in TOKEN.findall(value):
        if re.fullmatch(r"[\u4e00-\u9fff]+", match):
            result.extend(item.strip() for item in jieba.lcut(match, cut_all=False)
                          if item.strip())
        else:
            result.append(match)
    return result


class BM25:
    def __init__(self, tokenized, k1=1.5, b=0.75):
        self.tokens = tokenized
        self.k1, self.b = float(k1), float(b)
        self.lengths = np.asarray([len(row) for row in tokenized], dtype=np.float64)
        self.avgdl = float(self.lengths.mean()) if len(self.lengths) else 0.0
        self.counts = [Counter(row) for row in tokenized]
        self.df = Counter()
        for row in tokenized:
            self.df.update(set(row))

    def score(self, query):
        scores = np.zeros(len(self.tokens), dtype=np.float64)
        n = len(self.tokens)
        if not n or not self.avgdl:
            return scores
        for term in tokenize(query):
            freq = self.df.get(term, 0)
            if not freq:
                continue
            idf = math.log(1.0 + (n - freq + 0.5) / (freq + 0.5))
            for index, counts in enumerate(self.counts):
                tf = counts.get(term, 0)
                if tf:
                    denom = tf + self.k1 * (1 - self.b + self.b * self.lengths[index] / self.avgdl)
                    scores[index] += idf * tf * (self.k1 + 1) / denom
        return scores

    def serializable(self):
        return {"k1": self.k1, "b": self.b, "tokens": self.tokens,
                "doc_lengths": self.lengths.astype(int).tolist(), "avgdl": self.avgdl,
                "document_frequency": dict(sorted(self.df.items()))}


def reciprocal_rank_fusion(bm25_order, dense_order, constant=60):
    scores = Counter()
    for order in (bm25_order, dense_order):
        for rank, index in enumerate(order, 1):
            scores[int(index)] += 1.0 / (constant + rank)
    return scores


class Retriever:
    def __init__(self, chunks, bm25, embeddings=None, encoder=None, candidate_k=20,
                 rrf_constant=60, default_mode="hybrid", default_k=5, gate_threshold=None):
        self.chunks = chunks
        self.by_id = {row["chunk_id"]: row for row in chunks}
        self.bm25 = bm25
        self.embeddings = embeddings
        self.encoder = encoder
        self.candidate_k = int(candidate_k)
        self.rrf_constant = int(rrf_constant)
        self.default_mode = default_mode
        self.default_k = int(default_k)
        self.gate_threshold = gate_threshold

    def _eligible(self, component=None, product_version=None):
        indexes = []
        wanted = component.lower() if component else None
        for index, row in enumerate(self.chunks):
            components = [item.lower() for item in row["component"]]
            if wanted and wanted not in components:
                continue
            scopes = row["version_scope"]
            if product_version and product_version not in scopes and "all-conceptual" not in scopes:
                continue
            indexes.append(index)
        return indexes

    def search(self, query, mode=None, top_k=None, component=None, product_version=None,
               apply_gate=True):
        mode = self.default_mode if mode in (None, "frozen") else mode
        top_k = self.default_k if top_k is None else int(top_k)
        if mode not in {"bm25", "dense", "hybrid"}:
            raise ValueError("mode must be frozen, bm25, dense or hybrid")
        if not 1 <= top_k <= 10:
            raise ValueError("top_k must be between 1 and 10")
        eligible = self._eligible(component, product_version)
        if not eligible:
            return {"status": "insufficient_evidence", "mode": mode, "items": [],
                    "gate_score": None}
        lexical = self.bm25.score(query)
        dense = None
        if self.embeddings is not None and self.encoder is not None:
            vector = self.encoder.encode([query], query=True)[0]
            dense = np.asarray(self.embeddings @ vector, dtype=np.float64)
        if mode in {"dense", "hybrid"} and dense is None:
            raise RuntimeError("Dense retrieval artifacts are unavailable")
        bm25_order = sorted(eligible, key=lambda idx: (-lexical[idx], self.chunks[idx]["chunk_id"]))
        dense_order = (sorted(eligible, key=lambda idx: (-dense[idx], self.chunks[idx]["chunk_id"]))
                       if dense is not None else [])
        if mode == "bm25":
            order = bm25_order
            fused = {}
        elif mode == "dense":
            order = dense_order
            fused = {}
        else:
            fused = reciprocal_rank_fusion(bm25_order[:self.candidate_k],
                                            dense_order[:self.candidate_k], self.rrf_constant)
            order = sorted(fused, key=lambda idx: (-fused[idx], self.chunks[idx]["chunk_id"]))
        gate_score = float(max(dense[idx] for idx in eligible)) if dense is not None else None
        evidence = bool(order)
        if apply_gate and self.gate_threshold is not None:
            evidence = gate_score is not None and gate_score >= float(self.gate_threshold)
        if apply_gate and not evidence:
            return {"status": "insufficient_evidence", "mode": mode, "items": [],
                    "gate_score": gate_score}
        items = []
        for rank, index in enumerate(order[:top_k], 1):
            row = dict(self.chunks[index])
            row.update({"rank": rank, "bm25_score": float(lexical[index]),
                        "dense_score": float(dense[index]) if dense is not None else None,
                        "rrf_score": float(fused.get(index, 0.0))})
            items.append(row)
        return {"status": "evidence_found", "mode": mode, "items": items,
                "gate_score": gate_score}
