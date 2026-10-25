# 部署入口

## 模块职责

保存镜像健康检查以及 Docker Compose 配套脚本。

## 依赖边界

仅负责部署和健康检查，运行配置来自 resources/configs。

## Python 文件说明

| 文件 | 主要功能 | 主要类或函数 |
| --- | --- | --- |
| `healthcheck.py` | 实现 healthcheck 相关的辅助流程。 | — |

## 阅读建议

先阅读配置或 Schema，再阅读核心引擎，最后查看 `workflow.py`、`__main__.py` 或验收脚本了解完整调用顺序。文件内的中文注释重点解释职责、输入参数、数据字段和关键约束。
