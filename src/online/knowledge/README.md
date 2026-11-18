# 知识检索

## 模块职责

构建知识语料、混合检索、证据门控、检索指标与知识库发布；生成式问答在 `generation/`，v1.1 评测数据流水线在 `src/evaluation/retrieval/`。

## 依赖边界

向诊断层提供只读检索接口，不依赖 Agent 和服务层。

## Python 文件说明

| 文件 | 主要功能 | 主要类或函数 |
| --- | --- | --- |
| `__init__.py` | 定义当前包的公共入口、版本或导出符号。 | — |
| `__main__.py` | 实现 `python -m` 命令行入口和参数分发。 | `main` |
| `corpus.py` | 加载知识卡并切分为带稳定 chunk_id 的语料。 | `normalized`、`load_cards`、`load_sources`、`validate_corpus`、`evidence_units`、`chunk_structured` 等 |
| `dense.py` | 封装 BGE ONNX 向量编码和相似度计算。 | `OnnxEncoder` |
| `engine.py` | 词法 BM25、向量召回与倒数排名融合。 | `tokenize`、`BM25`、`reciprocal_rank_fusion`、`Retriever` |
| `evaluation.py` | 计算检索指标、门禁阈值与查询集校验。 | `validate_queries`、`evaluate`、`choose_gate` |
| `gate.py` | 用首条证据的稠密相似度做门控，并在开发与校准切分上标定阈值。 | `GatedRetriever`、`calibrate` |
| `jsonl.py` | v1.1 复核流程共用的 JSONL 读写。 | `read_rows`、`write_rows` |
| `protocol.py` | 校验 v1.1 评测协议的三份密封切分、来源版本与查询泄漏。 | `validate_protocol`、`SPLITS` |
| `release.py` | 校验并生成当前模块的不可变发布清单。 | `verify`、`FrozenRetriever` |
| `retrieval.py` | 组织"建库—评测—发布"的端到端流程与文件产物。 | `validate`、`fetch_model`、`validate_model_export`、`build`、`_load_engine` 等 |
| `review_schema.py` | 题包与回传文件的字段约定。 | `VISIBLE`、`REVIEW` |
| `settings.py` | 读取检索配置：知识卡目录、语料与发布产物路径。 | `load` |

子目录：`generation/` 是知识驱动的报告生成。

## 阅读建议

先读 `corpus.py` 弄清一条知识卡怎么变成可检索的 chunk，再看 `engine.py` 的召回与融合；`retrieval.py` 是把这些步骤和发布串起来的入口。
