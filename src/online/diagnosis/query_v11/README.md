# v1.1 查询规划

## 模块职责

构建确定性检索查询并执行 v1.1 Agent 评测与发布。

## 依赖边界

只通过知识检索接口取证，禁止 LLM 自由选择工具。

## Python 文件说明

| 文件 | 主要功能 | 主要类或函数 |
| --- | --- | --- |
| `__init__.py` | 定义当前包的公共入口、版本或导出符号。 | — |
| `engine.py` | 封装当前模块的核心执行引擎和稳定调用接口。 | `CandidateSummary`、`AgentEngine` |
| `evaluation.py` | 计算当前模块的评测指标并输出结构化结果。 | `classify_run`、`classify_summary` |
| `online_evaluation.py` | 执行受预算约束的在线报告评测。 | `_percentile`、`_usage_delta`、`_over_limit`、`_budget`、`_case_input`、`_inspect`、`_one_round`、`run` |
| `query_builder.py` | 从脱敏日志信号构建确定性检索计划。 | `load_config`、`RetrievalQueryBuilder` |
| `release.py` | 校验并生成当前模块的不可变发布清单。 | `_code_hashes`、`_inputs`、`_package_metadata`、`_dependency_hashes`、`_deployment_hashes`、`_query_builder`、`publish`、`verify` |
| `report_cases.py` | 提供报告链开发与回归案例。 | `ReadOnlyDatabase`、`_spaced_ids`、`build` |
| `tools.py` | 实现 tools 相关的辅助流程。 | `CandidateAgentTools` |

## 阅读建议

先阅读配置或 Schema，再阅读核心引擎，最后查看 `workflow.py`、`__main__.py` 或验收脚本了解完整调用顺序。文件内的中文注释重点解释职责、输入参数、数据字段和关键约束。
