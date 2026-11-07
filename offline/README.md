# 离线数据流程

本目录按离线流程划分为四个二级子目录：

| 子目录 | 职责 |
| --- | --- |
| `__init__.py` | 一级包入口，导出四个离线子流程。 |
| `capture` | 故障注入、正常采集、incident 与证据落盘 |
| `ingestion` | 多格式 adapter、规范化、滑动窗口 |
| `detection` | 按来源 Drain3 模板、severity-first 门禁、event |
| `evaluation` | 检测 FPR/Recall、事件/证据/引用评测 |

入口代码仍复用 `src/aiops_diag` 和 `ops`，这里提供稳定的离线流程边界和公共导出。
