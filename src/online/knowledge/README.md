# 知识检索

## 模块职责

构建知识语料、混合检索、门禁、评测和知识库发布。

## 依赖边界

向诊断层提供只读检索接口，不依赖 Agent 和服务层。

## Python 文件说明

| 文件 | 主要功能 | 主要类或函数 |
| --- | --- | --- |
| `__init__.py` | 定义当前包的公共入口、版本或导出符号。 | — |
| `__main__.py` | 实现 `python -m` 命令行入口和参数分发。 | `main` |
| `blind_v11.py` | 执行 v1.1 揭盲与一次性测试结果整理。 | `_read_sealed_test`、`_summarize`、`_groups`、`run` |
| `candidate_pool_v11.py` | 构造、校验和冻结 v1.1 候选题池。 | `_rows`、`_normalized`、`_knowledge_units`、`validate`、`build_packet` |
| `config.py` | 读取、校验并规范化当前模块的 YAML 配置。 | `load` |
| `corpus.py` | 加载知识卡并切分为带稳定 chunk_id 的语料。 | `normalized`、`load_cards`、`load_sources`、`validate_corpus`、`evidence_units`、`_chunk_id`、`_metadata`、`chunk_structured` 等 |
| `coverage_v11.py` | 统计知识卡对问题族和组件的覆盖。 | `compare` |
| `dense.py` | 封装 BGE ONNX 向量编码和相似度计算。 | `OnnxEncoder` |
| `engine.py` | 封装当前模块的核心执行引擎和稳定调用接口。 | `tokenize`、`BM25`、`reciprocal_rank_fusion`、`Retriever` |
| `evaluation.py` | 计算当前模块的评测指标并输出结构化结果。 | `validate_queries`、`_percentile`、`evaluate`、`choose_gate` |
| `freeze_reviewed_v11.py` | 冻结完成复核的 v1.1 数据集与哈希。 | `_relative`、`freeze` |
| `gate_v11.py` | 执行 v1.1 有答案与无答案检索门禁。 | `choose_gate_candidate`、`CandidateRetriever`、`calibrate_candidate` |
| `protocol_v11.py` | 定义 v1.1 检索校准、盲测和冻结协议。 | `_inside`、`_read_jsonl`、`_normalized`、`validate_protocol` |
| `release.py` | 校验并生成当前模块的不可变发布清单。 | `verify`、`FrozenRetriever` |
| `review_v11.py` | 合并复核意见并生成分歧清单。 | `_rows`、`_units`、`validate_packet`、`validate_submission` |
| `runbook_review_v11.py` | 检查知识卡与运行手册覆盖关系。 | `_rows`、`_write_rows`、`_sealed_cases`、`_log_sample`、`build`、`evaluate` |
| `workflow.py` | 组织当前模块的端到端工作流和文件产物。 | `_model_files`、`validate`、`fetch_model`、`validate_model_export`、`_write_build`、`build`、`_load_engine`、`_inputs_hash` 等 |

## 阅读建议

先阅读配置或 Schema，再阅读核心引擎，最后查看 `workflow.py`、`__main__.py` 或验收脚本了解完整调用顺序。文件内的中文注释重点解释职责、输入参数、数据字段和关键约束。
