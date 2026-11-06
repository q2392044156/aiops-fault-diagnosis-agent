# 框架化诊断

## 模块职责

用 LangChain、LangGraph 和 checkpoint 适配实现候选诊断流程。

## 依赖边界

数据库仍是任务、预算和审批的权威来源。

## Python 文件说明

| 文件 | 主要功能 | 主要类或函数 |
| --- | --- | --- |
| `__init__.py` | 定义当前包的公共入口、版本或导出符号。 | — |
| `checkpoint.py` | 保存和恢复 LangGraph 图进度快照。 | `DatabaseCheckpointSaver` |
| `evaluation.py` | 计算当前模块的评测指标并输出结构化结果。 | `_jsonl`、`evaluate_public_data`、`evaluate_runtime`、`markdown_report` |
| `graph.py` | 定义 LangGraph 节点、分支和状态流转。 | `GraphRunState`、`LangGraphAgentEngine` |
| `release.py` | 校验并生成当前模块的不可变发布清单。 | `_base`、`_code_hashes`、`_dependencies`、`_deployment`、`_package`、`_prior_observation`、`_value`、`publish` 等 |
| `release_v12.py` | 冻结并校验 v1.2 RC 发布清单。 | `_value`、`publish`、`verify` |
| `report_chain.py` | 用 LangChain 组织提示词、结构化输出和降级。 | `_provider_messages`、`CandidateSummaryChain` |
| `retriever.py` | 把现有混合检索器适配为 LangChain Retriever。 | `LangChainRetrieverAdapter` |
| `tools_v12.py` | v1.2 只读工具扩展点（Trace 能力已移除）。 | `V12AgentTools` |

## 阅读建议

先阅读配置或 Schema，再阅读核心引擎，最后查看 `workflow.py`、`__main__.py` 或验收脚本了解完整调用顺序。文件内的中文注释重点解释职责、输入参数、数据字段和关键约束。
