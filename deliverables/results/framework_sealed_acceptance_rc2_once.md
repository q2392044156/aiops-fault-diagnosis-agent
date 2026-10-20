# Framework RC2 30 例一次性封存验收

- 正式运行时间：`2026-10-20T07:31:21.791105+00:00`
- 候选发布：`agrfw_f92678b1ee9f51fa121afff9`
- 该集合现已揭盲，不得用于后续调参或再次正式验收。
- F/G/H 是流程隔离的 AI 角色，并非身份核验的自然人。

## 指标

- 流程完成：30/30
- 有答案错误拒答：0/18
- 知识库外错误返回：0/12 （0.00%）
- Recall / MRR / NDCG：1.0000 / 0.8889 / 0.9043
- Schema 合法：30/30
- 模板降级：0/30
- legacy/framework 等价：30/30
- Framework LLM 调用 / tokens / 费用：18 / 1584 / 0.00000000 CNY
- Framework 耗时 P50 / P95：577.695 / 620.250 ms

## 发布门禁

- thirty_of_thirty_flow_completed：`True`
- framework_adds_no_crash_or_safety_failure：`True`
- all_differences_attributed：`True`
- six_primary_and_two_recovery_hard_gates_zero：`True`

最终判定：`PASS`。
