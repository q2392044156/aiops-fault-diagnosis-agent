# Agent 评测包

## 模块职责

围绕一次诊断请求做端到端评测：跑用例、判定终态、按预算跑在线复核、给失败分类，并从运行库里取干净的报告用例。

## 依赖边界

允许同时依赖 `online.diagnosis` 与 `online.knowledge`，这两个包不得反向依赖本包。

## Python 文件说明

| 文件 | 主要职责 | 主要接口 |
| --- | --- | --- |
| `__init__.py` | 定义本包的公开入口与职责说明。 | — |
| `budget.py` | 把两次账本读数之差与配置上限比较，作为评测预算闸门。 | `usage_delta`、`over_budget` |
| `cases.py` | 从服务库只读取稳定的报告用例，按间距抽样本。 | `ReadOnlyDatabase`、`build` |
| `legacy.py` | v1.0 端到端评测编排：逐用例判定终态、在线复核与指标汇总。 | `EvalAction`、`EvalReport`、`deterministic_status`、`evaluate` |
| `online.py` | 在线复核评测：逐轮跑候选 Agent，核对复核结论与预算。 | `run` |
| `taxonomy.py` | 把失败运行归类到固定错误分类，并汇总分布。 | `classify_run`、`classify_summary`、`ERROR_CATEGORIES` |

## 阅读建议

先看 `legacy.py` 的 `evaluate`，它定义了一次评测的完整回合；`online.py` 是同一套指标在真实模型上的复现；`budget.py` 与 `cases.py` 是它的两个输入约束；`taxonomy.py` 解释失败怎么归类。
