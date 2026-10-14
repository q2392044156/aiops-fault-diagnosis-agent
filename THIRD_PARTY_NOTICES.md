# Third-party data notices

Source: https://github.com/logpai/loghub/blob/master/LICENSE
Pinned data: https://zenodo.org/records/8196385
Copied from the local research verification materials on 2026-10-09.
This notice applies to Loghub data, not an original-code license.

```text
LICENSE OF LOGHUB

The datasets are freely available for research or academic work, subject to
the following condition: For any usage or distribution of the loghub datasets,
please refer to the loghub repository URL (https://github.com/logpai/loghub)
and cite the following loghub paper where applicable.

Jieming Zhu, Shilin He, Pinjia He, Jinyang Liu, Michael R. Lyu. Loghub: A Large
Collection of System Log Datasets for AI-driven Log Analytics. In ISSRE, 2023.

The above license notice shall be included in all copies of the datasets.
```

## W2 software dependencies

W2 uses the following open-source Python packages. Their exact installed versions are recorded in `requirements-lock.txt`; their license files are included in the installed distributions.

- Drain3 — MIT License — https://github.com/logpai/Drain3
- scikit-learn — BSD 3-Clause License — https://github.com/scikit-learn/scikit-learn
- NumPy — BSD 3-Clause License — https://github.com/numpy/numpy
- SciPy — BSD 3-Clause License — https://github.com/scipy/scipy
- joblib — BSD 3-Clause License — https://github.com/joblib/joblib
- PyArrow — Apache License 2.0 — https://github.com/apache/arrow
- PyTorch — BSD-style License — https://github.com/pytorch/pytorch

## W7 documentation and retrieval model

- Apache Hadoop HDFS documentation — Apache License 2.0 — https://hadoop.apache.org/docs/
  Accessed 2026-10-13. The committed knowledge cards are original Chinese summaries;
  the upstream documentation is linked as evidence and is not copied wholesale.
- BAAI `bge-small-zh-v1.5` — MIT License —
  https://huggingface.co/BAAI/bge-small-zh-v1.5
  Pinned revision: `7999e1d3359715c523056ef9478215996d62a620`.
  Source `model.safetensors` SHA-256:
  `354763b9b1357bc9c44f62c6be2276321081ed2567773608c0d0785b61d5a026`.
  The locally exported FP32 ONNX artifact is not committed and is verified by the
  retrieval release manifest.
- Hugging Face Transformers, Tokenizers, Hub, Optimum ONNX and ONNX Runtime are
  used for model export or CPU inference. Their exact installed versions are
  recorded in the two requirements lock files.

## W8 report generation and optional reranker

- DeepSeek API (`deepseek-flash`) — commercial hosted API —
  https://api-docs.deepseek.com/
  W8 sends only the user's question and the W7 retrieved knowledge excerpts. API
  credentials are supplied at runtime from Docker secrets and are never included in
  source control, release manifests, reports or request logs.
- BAAI `bge-reranker-base` — MIT License —
  https://huggingface.co/BAAI/bge-reranker-base
  Pinned revision: `2cfc18c9415c912f9d8155881c133215df768a70`.
  Source `model.safetensors` SHA-256:
  `ced967c45fd1902eb92716c9ceeca7c95a936770ea9db611f5a841b926e33fbd`.
  The optional FP32 ONNX experiment is disabled by default; downloaded weights and
  exported artifacts remain under ignored local artifact directories.
