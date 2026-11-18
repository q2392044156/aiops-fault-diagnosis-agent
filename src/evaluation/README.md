# 评估层

## 模块职责

对离线检测与在线诊断做可复现的对照评测，产出结构化报告和数据表。

## 依赖边界

允许同时依赖 `offline` 与 `online`，但两者都不允许反向依赖它。评估只读不写生产库，所有产物落在 `artifacts/` 与 `experiments/` 下。

## Python 文件说明

| 文件 | 主要职责 | 主要入口 |
| --- | --- | --- |
| `__init__.py` | 定义本包的公开范围。 | 无 |
| `trajectory.py` | 统计诊断轨迹的阶段通过率与 pass^k。 | `aggregate`、`pass_pow_k`、`summarize`、`markdown` |
| `redteam.py` | 用注入与越权用例检查报告与工具边界。 | `evaluate`、`load_cases`、`markdown` |
| `router.py` | 评测工具路由的选路质量与自由路由提示。 | `score`、`markdown`、`FREE_PROMPT` |
| `comparison.py` | 框架候选与在线整链的对照运行与数据表。 | `run`、`_seed_agent_case` |

## 阅读建议

先看 `comparison.py` 的 `run` 弄清一次对照要准备哪些输入，再按需看 `trajectory.py`／`router.py` 的指标口径；`redteam.py` 的用例集在 `resources/redteam/` 下，改判据时同步改用例。
