# 故障事件契约

## 模块职责

定义 v1.2 真实故障事件的共享契约，并提供导入、审计、删除与受控实验记录的构造。

## 依赖边界

只依赖 `aiops_diag.common` 与 `aiops_diag.platform.db`；命令行入口在 `aiops_diag/platform`（`python -m aiops_diag.platform incident`）。

## Python 文件说明

| 文件 | 主要功能 | 主要类或函数 |
| --- | --- | --- |
| `__init__.py` | 定义当前包的公共入口、版本或导出符号。 | — |
| `contracts.py` | 定义 v1.2 故障事件的共享契约。 | `StrictModel`、`EvidenceRefV12`、`MetricEligibilityV12`、`ExternalEventV12`、`SafeLogTemplateV12`、`TraceSummaryV12`、`DiagnosticSnapshotV12`、`EvaluationLabelV12`、`IncidentRecordV1` 等 |
| `incident.py` | 校验 v1.2 真实故障事件协议和时间戳字段，并落库、审计与删除。 | `load_incident`、`metric_eligibility`、`validate_incident`、`import_incident`、`audit_incident`、`delete_incident` |
| `lab.py` | 构造受控实验的 incident 记录、脱敏证据与哈希。 | `build_incident`、`redact`、`write_evidence` |

## 阅读建议

先读 `contracts.py` 弄清一个事件必须有哪些字段，再看 `incident.py` 的 `validate_incident` 怎么拒绝不合规输入；`lab.py` 是反向的一条路——从真实日志造出能过校验的事件，用于本地复现。
