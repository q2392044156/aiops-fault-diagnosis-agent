# v1.2 评测摘要

## 公开数据

- 标准化事件：419
- Schema 校验记录：838
- 事件与标签一一对应：True
- 生产根因指标：N/A
- MTTD：N/A

### hdfs_v3_tracebench

- 事件：364
- 日志快照事件：0
- Trace 快照事件：364

### loghub_hadoop

- 事件：55
- 日志快照事件：55
- Trace 快照事件：0

## 运行时与安全门禁

- 诊断运行：3
- 报告：3
- Checkpoint：54
- 硬门禁通过：True

- illegal_reference_release: 0
- unauthorized_tool_call: 0
- execution_allowed_true: 0
- budget_breakthrough: 0
- insufficient_evidence_llm_call: 0
- mandatory_review_missed: 0
- duplicate_paid_call_after_recovery: 0
- conflicting_report_after_recovery: 0
- duplicate_approval_after_recovery: 0
- evaluation_label_leakage: 0

## 限制

公开注入标签不等同于经过工单和独立人员确认的生产根因。
公开 independent_test 是组隔离测试分区，不是严格封存盲测集。
