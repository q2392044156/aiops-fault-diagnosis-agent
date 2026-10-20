# Framework 离线对照开发集

本目录用于比较 v1.1 自定义状态机（`legacy`）与 Framework Candidate
（LangGraph 执行、LangChain 报告链和检索适配器）的离线行为。

## 边界

- 这些案例由项目开发方编写，可以反复运行和修改。
- 这些案例不是独立盲测集，不能用于证明检索质量或生产效果提升。
- 案例不读取 `evaluation/v1.2/blind_cde_20261020`，也不把已经揭盲的结果用于调参。
- 离线模型客户端返回固定的合法摘要，不访问 DeepSeek，不产生真实费用。
- 输出不保存日志原文、环境变量或密钥。

## 案例组成

`dev_cases.jsonl` 包含两类案例：

1. `retrieval`：直接比较现有候选检索器与 LangChain 适配器的状态、排序、
   `chunk_id`、门禁分数和引用元数据。
2. `agent`：在隔离 SQLite 和合成脱敏日志上跑完整诊断流程，比较终态、
   报告语义、工具顺序、预算、安全门禁和引用集合。

检索案例加载真实冻结索引。Agent 案例使用 `retrieval_fixture` 指定的确定性
证据或拒答结果，以便在不受当前检索门禁波动影响的情况下覆盖有证据报告链、
证据不足、提示注入和模板降级。夹具只用于流程等价性，不计为检索效果。

legacy 侧使用 `configs/service_v11_framework_base.yaml`。该配置是 Framework
Candidate 冻结时绑定的同源 v1.1 基线，便于只比较框架接入造成的差异。

`expected_status`、`expected_diagnosis_status` 等字段只是开发回归预期。
工具会把“两个后端是否一致”和“是否满足开发预期”分别报告。

## 运行

```powershell
.\.w10-env\Scripts\python.exe scripts\run_framework_offline_comparison.py
```

默认产物：

- `deliverables/results/framework_offline_comparison_rc1_02.json`
- `deliverables/results/framework_offline_comparison_rc1_02.md`

