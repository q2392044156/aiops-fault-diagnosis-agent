"""模块说明：封装 BGE ONNX 向量编码和相似度计算。"""

from pathlib import Path

import numpy as np


# 类说明：`OnnxEncoder` 封装本模块内聚的数据和行为。
class OnnxEncoder:
    # 方法说明：`__init__` 完成当前步骤的业务处理；参数为 `model_dir`、`query_prefix`、`max_length`、`batch_size`。
    def __init__(self, model_dir, query_prefix, max_length=512, batch_size=32):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        directory = Path(model_dir)
        self.tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=int(max_length))
        pad_id = self.tokenizer.token_to_id("[PAD]") or 0
        self.tokenizer.enable_padding(pad_id=pad_id, pad_token="[PAD]")
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(str(directory / "model.onnx"), options,
                                            providers=["CPUExecutionProvider"])
        self.input_names = {item.name for item in self.session.get_inputs()}
        self.query_prefix = query_prefix
        self.batch_size = int(batch_size)

    # 方法说明：`encode` 完成当前步骤的业务处理；参数为 `texts`、`query`。
    def encode(self, texts, query=False):
        values = []
        texts = [self.query_prefix + text if query else text for text in texts]
        for offset in range(0, len(texts), self.batch_size):
            encoded = self.tokenizer.encode_batch(texts[offset:offset + self.batch_size])
            feed = {
                "input_ids": np.asarray([item.ids for item in encoded], dtype=np.int64),
                "attention_mask": np.asarray([item.attention_mask for item in encoded],
                                             dtype=np.int64),
                "token_type_ids": np.asarray([item.type_ids for item in encoded], dtype=np.int64),
            }
            feed = {name: value for name, value in feed.items() if name in self.input_names}
            hidden = np.asarray(self.session.run(None, feed)[0], dtype=np.float32)
            cls = hidden[:, 0, :]
            norm = np.linalg.norm(cls, axis=1, keepdims=True)
            values.append(cls / np.maximum(norm, 1e-12))
        if not values:
            return np.empty((0, 0), dtype=np.float32)
        return np.concatenate(values, axis=0).astype(np.float32)
