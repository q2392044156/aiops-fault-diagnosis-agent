# 对照评测

## 模块职责

对 legacy 与 framework 流程执行归一化离线对照。

## 依赖边界

只读取公开接口和冻结案例，不修改业务状态。

## Python 文件说明

| 文件 | 主要功能 | 主要类或函数 |
| --- | --- | --- |
| `__init__.py` | 定义当前包的公共入口、版本或导出符号。 | — |
| `redteam.py` | 用真实防御逻辑评测红队用例的拦截率与误杀率。 | `evaluate`、`load_cases`、`markdown` |
| `trajectory.py` | 计算诊断轨迹的步骤、工具、证据与预算指标。 | `summarize`、`aggregate`、`classify`、`pass_pow_k`、`markdown` |
| `router_eval.py` | 计算工具路由的准确率、精确/召回与成本指标。 | `score`、`_per_tool`、`markdown` |
| `offline_framework.py` | 逐例比较 legacy 与 framework 的检索、工具和报告差异。 | `OfflineSummaryClient`、`OfflineCaseRetriever`、`_json_lines`、`load_cases`、`_finite`、`_retrieval_snapshot`、`_diff`、`_runtime` 等 |

## 阅读建议

先阅读配置或 Schema，再阅读核心引擎，最后查看 `workflow.py`、`__main__.py` 或验收脚本了解完整调用顺序。文件内的中文注释重点解释职责、输入参数、数据字段和关键约束。
