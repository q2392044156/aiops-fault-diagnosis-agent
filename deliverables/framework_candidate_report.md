# LangChain / LangGraph 框架候选实施与流程验收报告

## 结论

已完成一个与原 v1.0/v1.1 流程并存的框架候选，实现并跑通以下链路：

```text
冻结 BM25/BGE 检索
  → LangChain Document 适配（排序与门禁不变）
  → LangGraph 固定节点（数据库仍是状态权威）
  → LangChain 结构化摘要链
  → 原有 Schema、引用、安全、预算和人工复核门禁
```

候选发布标识为 `agrfw_ae81d2f59c07a4bd67f36bc9`，状态为
`READY_FOR_FLOW_VALIDATION`，并明确标记 `production_ready=false`。

新的 60 题盲测结果继续作为已揭盲的历史观察保留：知识库外错误返回
`16/39（41.03%）`。本阶段取消 10% 阈值作为“流程开发阻断条件”，没有将
该结果改写为质量达标，也没有重新运行或用它调参。

## 已实现内容

### 1. 独立依赖锁

- `langchain-core==1.6.12`
- `langgraph==1.2.16`
- 框架完整依赖保存于 `requirements-framework-lock.txt`
- 镜像构建执行 `pip check`，结果无依赖冲突

没有接入 `langchain-deepseek`。所有真实模型调用仍由项目原有
`DeepSeekClient`、预算台账、超时与失败审计负责。

### 2. LangChain 检索适配

`LangChainRetrieverAdapter` 直接包装现有 `CandidateRetriever`：

- 原有 `search()` 返回结构保持不变；
- LangChain `invoke()` 生成 `Document`；
- metadata 保留 `chunk_id`、版本、检索状态、门禁分数、知识库发布 ID 及冻结哈希；
- `insufficient_evidence` 映射为空文档列表，不绕过拒答门禁。

### 3. LangChain 报告链

`CandidateSummaryChain` 使用 `ChatPromptTemplate`、`RunnableLambda` 和
`PydanticOutputParser`，只允许模型生成一个保守摘要。候选原因、事实、检查项、
引用和限制继续由确定性程序产生。一次修复失败后仍回退模板。

在线合成证据冒烟结果：

- 结构化输出通过；
- 1 次 LLM 调用，481 tokens；
- 估算费用 `¥0.001172`；
- 非法模型引用 0；
- 可执行建议 0。

该结果只证明框架调用链可运行，不代表真实故障诊断效果。

### 4. LangGraph 固定节点

LangGraph 节点为：

1. `validate`
2. `detect`
3. `collect_evidence`
4. `retrieve`
5. `rank_candidates`
6. `generate_validate_report`
7. `publish_report`

每次 worker 租约只推进一个持久化阶段。工具选择仍由程序控制，未开放 LLM
自由调用工具。当前不启用 LangGraph checkpointer，SQLite 中的任务、工具审计、
预算、审批和恢复记录是唯一权威来源。

## 验收证据

| 验收项 | 结果 |
| --- | --- |
| 框架专项测试 | 9 项通过 |
| 全量回归 | 144 项通过；1 个既有 pytest 配置警告 |
| Compose 静态校验 | 通过 |
| 镜像依赖检查 | `pip check` 通过 |
| worker / api / ui 健康检查 | 全部 healthy |
| 实际批处理 | SUCCEEDED |
| 实际诊断流程 | WAITING_REVIEW / REPORT_VALIDATED |
| 工具调用 | 6 次，固定白名单内 |
| 重启后同键重放 | 批次和诊断均 deduplicated=true |
| 重启后重复工具调用 | 无，仍为 6 次 |
| 非法引用 | 0 |
| 可执行建议 | 0 |
| 预算突破 | 0 |

实际容器事件因检索门禁判为证据不足，流程正确跳过 LLM，并生成强制复核报告。
这证明了拒答分支的端到端行为；LangChain 在线生成分支由独立合成证据冒烟覆盖。

## 关键产物

- 框架配置：`configs/service_framework_candidate.yaml`
- 框架发布：`artifacts/releases/framework_v12_rc1_02/`
- v1.1 基础发布：`artifacts/releases/agent_v11_framework_base_rc1/`
- 容器覆盖配置：`deployment/compose.framework-candidate.yaml`
- 首次流程结果：`deliverables/results/framework_flow_smoke_rc1_02.json`
- 重启重放结果：`deliverables/results/framework_flow_smoke_after_restart_rc1_02.json`
- LangChain 在线结果：`deliverables/results/framework_langchain_online_smoke_rc1_02.json`

## 运行与回退

框架候选使用本机端口 `28000`（API）和 `28501`（UI）。当前容器已启动。

框架候选通过独立 Compose 覆盖文件运行。回退时停止该 Compose 项目，再使用
原 `deployment/compose.yaml` 或 `deployment/compose.v11-candidate.yaml` 启动旧后端；
两个旧发布目录没有被覆盖。

## 尚未完成

- 41.03% 的知识库外错误返回仍需新校准集和另一套未揭盲测试集解决；
- 尚未对 LangGraph checkpoint 做双写、恢复与迁移验证；
- 尚未完成真实根因标签、MTTD、企业身份认证、TLS、外部数据库和队列；
- C/D/E 仍是流程隔离的 AI 角色，不等同于真实独立人员签署。

因此该候选适合继续做框架对照和流程开发，不应作为生产发布。
