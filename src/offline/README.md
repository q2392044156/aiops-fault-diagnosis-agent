# 离线数据流程

本目录按离线流程划分为三个二级子目录：

| 子目录 | 职责 |
| --- | --- |
| `__init__.py` | 一级包入口，导出三个离线子流程。 |
| `ingestion` | 多格式 adapter、规范化、滑动窗口、事件入库 |
| `detection` | 按来源 Drain3 模板、severity-first 门禁、LR/LSTM 检测 |

三个子包即全部实现，没有第二份副本。服务侧只用到 `ingestion`（`parser`）与 `detection`（`templates`、`config`）里的少数几个函数；故障注入与采集脚本留在 `ops/lab/`。
