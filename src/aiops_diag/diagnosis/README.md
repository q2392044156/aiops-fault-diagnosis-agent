# 诊断编排

## 模块职责

执行只读工具、预算控制、审批与确定性诊断工作流。

## 依赖边界

组合检测、检索和报告生成能力，不被下层模块反向引用。

## Python 文件说明

| 文件 | 主要功能 | 主要类或函数 |
| --- | --- | --- |
| `__init__.py` | 定义当前包的公共入口、版本或导出符号。 | — |
| `__main__.py` | 实现 `python -m` 命令行入口和参数分发。 | `main` |
| `auth.py` | 校验复核人员身份、角色和审批令牌。 | `ReviewerAuthError`、`token_hash`、`ReviewerRegistry`、`initialize_reviewer` |
| `budget.py` | 预留、结算并审计模型调用预算。 | `DatabaseBudgetLedger` |
| `config.py` | 读取、校验并规范化当前模块的 YAML 配置。 | `load` |
| `engine.py` | 封装当前模块的核心执行引擎和稳定调用接口。 | `AgentYield`、`utcnow`、`AgentEngine` |
| `release.py` | 校验并生成当前模块的不可变发布清单。 | `code_hashes`、`publish`、`verify` |
| `schemas.py` | 定义当前模块输入输出的 Pydantic 数据结构。 | `StrictModel`、`ToolResult`、`Evidence`、`Hypothesis`、`ActionAdvice`、`GeneratedReportBody`、`IncidentReport`、`RouterDecision` |
| `tools.py` | 定义只读工具白名单、调用审计和结果契约。 | `result`、`AgentTools`、`log_evidence`、`document_evidence` |
| `workflow.py` | 组织当前模块的端到端工作流和文件产物。 | `EvalAction`、`EvalReport`、`load_cases`、`validate_isolation`、`deterministic_status`、`_usage_delta`、`_budget_used`、`_atest_online` 等 |

## 阅读建议

先阅读配置或 Schema，再阅读核心引擎，最后查看 `workflow.py`、`__main__.py` 或验收脚本了解完整调用顺序。文件内的中文注释重点解释职责、输入参数、数据字段和关键约束。
