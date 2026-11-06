# 数据接入

## 模块职责

下载、解析、脱敏、审计并导入 HDFS 日志与真实故障事件。

## 依赖边界

只生成标准数据对象，不依赖检测、诊断或服务层。

## Python 文件说明

| 文件 | 主要功能 | 主要类或函数 |
| --- | --- | --- |
| `__init__.py` | 定义当前包的公共入口、版本或导出符号。 | — |
| `__main__.py` | 实现 `python -m` 命令行入口和参数分发。 | `_legacy`、`_external`、`_incident`、`main` |
| `audit.py` | 检查原始数据哈希、来源、许可证、脱敏状态和污染风险。 | `audit` |
| `common.py` | 提供数据模块共享的哈希、路径和序列化工具。 | `digest`、`canonical`、`key`、`save`、`config`、`verified_manifest` |
| `download.py` | 按来源清单下载并校验公开数据文件。 | `fetch`、`extract`、`download`、`_download` |
| `lab.py` | 构造受控实验的 incident 记录、脱敏证据与哈希。 | `build_incident`、`redact`、`write_evidence` |
| `incident_v12.py` | 校验 v1.2 真实故障事件协议和时间戳字段。 | `load_incident`、`metric_eligibility`、`validate_incident`、`import_incident`、`audit_incident`、`delete_incident` |
| `parser.py` | 解析 LogHub HDFS 日志并生成统一记录。 | `timestamp`、`parse`、`normalized` |
| `pipeline.py` | 串联原始日志解析、划分、注册和数据清单生成。 | `location`、`semantic_config`、`connect`、`finish`、`build`、`split`、`subset`、`trace` |
| `v12_contracts.py` | 定义 v1.2 故障事件的共享契约。 | `StrictModel`、`EvidenceRefV12`、`MetricEligibilityV12`、`ExternalEventV12`、`SafeLogTemplateV12`、`TraceSummaryV12`、`DiagnosticSnapshotV12`、`EvaluationLabelV12` 等 |

## 阅读建议

先阅读配置或 Schema，再阅读核心引擎，最后查看 `workflow.py`、`__main__.py` 或验收脚本了解完整调用顺序。文件内的中文注释重点解释职责、输入参数、数据字段和关键约束。
