# 数据接入

## 模块职责

下载、解析、脱敏、审计并划分 HDFS 日志：把原始日志变成 canonical 行与时间窗。

## 依赖边界

只生成标准数据对象，不依赖检测、诊断或服务层。事件契约与导入在 `offline/case/`。

## Python 文件说明

| 文件 | 主要功能 | 主要类或函数 |
| --- | --- | --- |
| `__init__.py` | 定义当前包的公共入口、版本或导出符号。 | — |
| `__main__.py` | 实现 `python -m` 命令行入口和参数分发。 | `_legacy`、`main` |
| `audit.py` | 检查原始数据哈希、来源、许可证、脱敏状态和污染风险。 | `audit` |
| `canonical.py` | 定义跨来源日志的统一字段并补齐缺失字段。 | `CANONICAL_FIELDS`、`canonical_log`、`is_parsed` |
| `adapters.py` | 按来源解析 HDFS_v1、Docker、WSL 日志。 | `parse_line`、`parse_lines`、`parse_hdfs_v1`、`parse_container` |
| `windows.py` | 按时间、组件和最大行数生成统一窗口。 | `make_windows`、`load_case_windows`、`load_normal_windows` |
| `download.py` | 按来源清单下载并校验公开数据文件。 | `fetch`、`extract`、`download`、`_download` |
| `parser.py` | 解析 LogHub HDFS 日志并生成统一记录。 | `timestamp`、`parse`、`normalized` |
| `pipeline.py` | 串联原始日志解析、划分、注册和数据清单生成。 | `location`、`semantic_config`、`connect`、`finish`、`build`、`split`、`subset`、`trace` |

`common.py` 在 `src/aiops_diag/common.py`，由离线和在线流程共同引用。

## 阅读建议

先读 `parser.py` 与 `adapters.py` 弄清一行日志怎么变成 canonical 记录，再看 `windows.py` 怎么切窗；`pipeline.py` 是这些步骤的串行编排，`audit.py` 守着数据合规。
