# Framework RC2 在线服务验收

- 运行时间：`2026-10-20T07:30:20.306539+00:00`
- 发布：`agrfw_f92678b1ee9f51fa121afff9`
- 路径：FastAPI → SQLite 队列 → worker → 冻结索引 → LangChain → LangGraph → DeepSeek。
- 输入是合成脱敏开发案例，不是生产效果证明。

- 完成：18/18
- Schema 合法：18/18
- 模板降级：0/18
- LLM 调用：18，tokens：22318，费用：0.04938800 CNY
- P50 / P95：1613.997 / 2000.712 ms

## 安全门禁

- invalid_citations：`0`
- unauthorized_tools：`0`
- execution_allowed：`0`
- budget_exceeded：`0`
- insufficient_evidence_llm_calls：`0`
- required_review_missing：`0`

结论：`PASS`。
