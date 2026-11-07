# 报告生成

## 模块职责

根据已验证证据生成、校验并降级诊断报告。

## 依赖边界

依赖知识检索结果和模型客户端，不负责工具调度。

## Python 文件说明

| 文件 | 主要功能 | 主要类或函数 |
| --- | --- | --- |
| `__init__.py` | 定义当前包的公共入口、版本或导出符号。 | — |
| `__main__.py` | 实现 `python -m` 命令行入口和参数分发。 | `main` |
| `client.py` | 封装 DeepSeek HTTP 调用、超时和错误处理。 | `BudgetExceeded`、`DeepSeekError`、`DeepSeekJsonError`、`_secret`、`BudgetLedger`、`DeepSeekClient` |
| `config.py` | 读取、校验并规范化当前模块的 YAML 配置。 | `load` |
| `engine.py` | 封装当前模块的核心执行引擎和稳定调用接口。 | `_canonical_hash`、`RagEngine` |
| `release.py` | 校验并生成当前模块的不可变发布清单。 | `verify`、`public` |
| `reranker.py` | 对检索候选执行确定性重排。 | `OnnxReranker`、`RerankedRetriever` |
| `schemas.py` | 定义当前模块输入输出的 Pydantic 数据结构。 | `StrictModel`、`EvidenceClaim`、`RecommendedCheck`、`GeneratedBody`、`EvidenceReference`、`Provenance`、`RagReport` |
| `workflow.py` | 组织当前模块的端到端工作流和文件产物。 | `validate`、`_score`、`_run_split`、`tune`、`publish`、`finalize`、`fetch_reranker`、`benchmark` |

## 阅读建议

先阅读配置或 Schema，再阅读核心引擎，最后查看 `workflow.py`、`__main__.py` 或验收脚本了解完整调用顺序。文件内的中文注释重点解释职责、输入参数、数据字段和关键约束。
