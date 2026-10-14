from pathlib import Path

import numpy as np


class OnnxReranker:
    def __init__(self, model_dir, max_length=512, batch_size=8):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        directory = Path(model_dir)
        self.tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=int(max_length))
        pad_id = self.tokenizer.token_to_id("<pad>")
        if pad_id is None:
            pad_id = self.tokenizer.token_to_id("[PAD]") or 0
        pad_token = self.tokenizer.id_to_token(pad_id) or "<pad>"
        self.tokenizer.enable_padding(pad_id=pad_id, pad_token=pad_token)
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(str(directory / "model.onnx"), options,
                                            providers=["CPUExecutionProvider"])
        self.input_names = {item.name for item in self.session.get_inputs()}
        self.batch_size = int(batch_size)

    def score(self, query, documents):
        values = []
        pairs = [(query, text) for text in documents]
        for offset in range(0, len(pairs), self.batch_size):
            encoded = self.tokenizer.encode_batch(pairs[offset:offset + self.batch_size])
            feed = {"input_ids": np.asarray([item.ids for item in encoded], dtype=np.int64),
                    "attention_mask": np.asarray([item.attention_mask for item in encoded],
                                                 dtype=np.int64),
                    "token_type_ids": np.asarray([item.type_ids for item in encoded],
                                                  dtype=np.int64)}
            feed = {name: value for name, value in feed.items() if name in self.input_names}
            logits = np.asarray(self.session.run(None, feed)[0], dtype=np.float32).reshape(-1)
            values.extend(float(value) for value in logits)
        return np.asarray(values, dtype=np.float32)


class RerankedRetriever:
    def __init__(self, base, reranker, candidate_k=10, output_k=3):
        self.base = base
        self.reranker = reranker
        self.candidate_k = int(candidate_k)
        self.output_k = int(output_k)

    def search(self, query, mode=None, top_k=None, component=None, product_version=None,
               apply_gate=False):
        result = self.base.search(query, mode="hybrid", top_k=self.candidate_k,
                                  component=component, product_version=product_version,
                                  apply_gate=apply_gate)
        items = result["items"]
        if not items:
            return result
        scores = self.reranker.score(query, [row["text"] for row in items])
        order = sorted(range(len(items)), key=lambda index: (-scores[index],
                                                             items[index]["chunk_id"]))
        limit = self.output_k if top_k is None else min(int(top_k), self.output_k)
        reranked = []
        for rank, index in enumerate(order[:limit], 1):
            row = dict(items[index])
            row["rank"] = rank
            row["reranker_score"] = float(scores[index])
            reranked.append(row)
        return {**result, "mode": "hybrid_reranked", "items": reranked}
