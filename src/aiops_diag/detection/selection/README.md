# 模型选择

## 模块职责

按冻结协议比较候选检测器并输出选择结果。

## 依赖边界

依赖检测模块的评测产物，通过文件契约解耦训练过程。

## Python 文件说明

| 文件 | 主要功能 | 主要类或函数 |
| --- | --- | --- |
| `__init__.py` | 定义当前包的公共入口、版本或导出符号。 | — |
| `__main__.py` | 实现 `python -m` 命令行入口和参数分发。 | `main` |
| `config.py` | 读取、校验并规范化当前模块的 YAML 配置。 | `load`、`resolved` |
| `workflow.py` | 比较候选模型并根据冻结规则选择发布模型。 | `_git_commit`、`_read`、`_stage`、`_publish_stage`、`_runs`、`_assignments`、`_validation_predictions`、`_selection_decision` 等 |

## 阅读建议

先阅读配置或 Schema，再阅读核心引擎，最后查看 `workflow.py`、`__main__.py` 或验收脚本了解完整调用顺序。文件内的中文注释重点解释职责、输入参数、数据字段和关键约束。
