# Framework RC2 故障注入与恢复验收

- 运行时间：`2026-10-20T07:27:12.118147+00:00`
- pytest 退出码：`0`

## 场景组

- `query_safety`：1 个测试选择器，`PASS`
- `report_validation_and_fallback`：9 个测试选择器，`PASS`
- `provider_failures`：3 个测试选择器，`PASS`
- `tool_and_budget_failures`：3 个测试选择器，`PASS`
- `recovery_and_idempotency`：8 个测试选择器，`PASS`
- `langgraph_and_real_index`：2 个测试选择器，`PASS`

## 恢复硬门禁

- invalid_citations：`0`
- unauthorized_tools：`0`
- execution_allowed：`0`
- budget_exceeded：`0`
- insufficient_evidence_llm_calls：`0`
- required_review_missing：`0`
- duplicate_paid_calls_after_recovery：`0`
- conflicting_reports_or_approvals_after_recovery：`0`

这些计数来自自动化断言；服务在线 18 次运行单独报告。
