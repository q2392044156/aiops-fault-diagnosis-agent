# 数据接入

## 模块职责

解析、脱敏并划分 HDFS 日志：把原始日志变成 canonical 行、脱敏文本与时间窗。

## 依赖边界

只生成标准数据对象，不依赖检测、诊断或服务层。事件契约与导入在 `offline/case/`。

## Python 文件说明

| 文件 | 主要功能 | 主要类或函数 |
| --- | --- | --- |
| `__init__.py` | 定义当前包的公共入口、版本或导出符号。 | — |
| `canonical.py` | 定义跨来源日志的统一字段并补齐缺失字段。 | `CANONICAL_FIELDS`、`canonical_log`、`is_parsed` |
| `adapters.py` | 按来源解析 HDFS_v1、Docker、WSL 日志。 | `parse_line`、`parse_lines`、`parse_hdfs_v1`、`parse_container` |
| `windows.py` | 按时间、组件和最大行数生成统一窗口。 | `make_windows`、`load_case_windows`、`load_normal_windows` |
| `parser.py` | 解析 LogHub HDFS 日志并生成统一记录。 | `timestamp`、`parse`、`normalized` |
| `redact.py` | 用正则抹掉 block、IP、路径、十六进制与长数字，并给出稳定形态编号。 | `content`、`shape_id`、`masking_spec`、`RULES` |

`common.py` 在 `src/aiops_diag/common.py`，由离线和在线流程共同引用。

## 阅读建议

先读 `parser.py` 与 `adapters.py` 弄清一行日志怎么变成 canonical 记录，再看 `redact.py` 怎么做脱敏与形态编号，最后看 `windows.py` 怎么切窗。
