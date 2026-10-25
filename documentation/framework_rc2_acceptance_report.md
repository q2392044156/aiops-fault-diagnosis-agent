# v1.1 Framework RC2 总验收报告

## 1. 结论

`v1.1-framework-rc2` 已达到本项目定义的 **v1.2 准入条件**，可作为默认研究后端使用，同时保留 legacy 回退。该结论表示框架迁移、流程、安全门禁、恢复与部署路径已经跑通，不表示系统已经达到生产部署要求，也不表示真实根因诊断效果已经得到验证。

| 项目 | 结果 |
| --- | --- |
| Framework 发布 | `agrfw_f92678b1ee9f51fa121afff9` |
| legacy 基础发布 | `agr11_2c22bb514af4d49743293f8a` |
| 产品 / 包版本 | `v1.1-framework-rc2` / `1.1.0rc2` |
| 默认后端 | `framework_candidate` + `langgraph` + `langchain` |
| 全量测试 | 158 passed，1 个既有 pytest 配置警告 |
| 安全硬门禁 | 8 项计数全部为 0 |
| legacy 回退 | 演练通过，无数据库迁移 |
| v1.2 数据协议 | 已冻结，协议哈希 `b89e0d0f3738c31e3535c242cd291b9af46eae87eb1356d8b81f350cbb1497b5` |

## 2. 实现内容

### 2.1 确定性检索查询构建

新增 `RetrievalQueryBuilder` 与 `query_builder_v1` 配置，只从脱敏后的组件、等级、产品版本、信号次数和白名单异常信号构建查询。它不会把任意日志原文、URL、命令、路径、提示注入或密钥样式文本直接拼入检索查询。

支持的核心信号包括 safe mode、心跳缺失、block report 延迟、failed volume、副本不足、JournalNode 多数派异常、NameNode 不可用、standby 延迟、写入 pipeline 与 lease recovery。多组件事件稳定排序后最多生成三个计划，结果按计划与原始排序合并，并按 `chunk_id` 去重。

第一阶段没有修改冻结知识库、BGE ONNX、BM25、RRF 或检索阈值。工具审计保存查询计划、构建版本、标准信号和拒答原因，不保存原始日志。

### 2.2 LangChain 与 LangGraph

- LangChain 负责冻结检索器的文档适配、提示词、DeepSeek JSON 调用、Pydantic Schema 校验、一次修复和模板降级。
- LangGraph 表达固定诊断节点与条件分支，并记录节点执行次数。
- SQLite 继续负责任务、工具序号、预算、审批、审计和恢复，是唯一权威状态来源。
- LLM 自由工具路由关闭；所有工具选择保持确定性。
- LangGraph checkpoint 延后到 v1.2，避免在 RC2 同时引入第二套恢复权威状态。

### 2.3 默认后端与回退

默认研究服务配置为 `configs/service_framework_rc2.yaml`：

```yaml
agent_backend: framework_candidate
execution_backend: langgraph
report_backend: langchain
retrieval_backend: langchain
```

普通 API 请求不能选择后端。切换仅在服务启动配置中完成。已验证的 legacy 回退组合使用 `configs/service_v11_framework_base_rc2.yaml`，不迁移数据库，也不重跑已完成任务。

## 3. 验收结果

### 3.1 离线双层对照

| 层 | 案例 | 流程完成 | framework / legacy 一致 | 开发预期 |
| --- | ---: | ---: | ---: | ---: |
| 流程隔离固定夹具 | 12 | 12/12 | 12/12 | 10/10 |
| 真实冻结索引 | 12 | 12/12 | 12/12 | 12/12 |

固定夹具层用于定位框架自身差异。其中两条旧的直接检索问题 `ret_namenode_safemode`、`ret_journal_majority` 仍被现有门禁拒答；这不被写成质量改善。真实 Agent 流程通过新的确定性查询构建器取得对应证据，NameNode safe mode、DataNode 心跳、failed volume、JournalNode 多数派、NameNode 不可用以及 block report 案例均进入报告链。知识库外、空日志和提示注入案例没有触发 LLM。

该层是开发回归数据，不是独立效果评测。

### 3.2 在线 DeepSeek 服务链路

通过 FastAPI、SQLite 队列、worker、真实冻结索引、LangChain、LangGraph 和真实 DeepSeek 配置运行 6 个有证据案例，每例 3 次。

| 指标 | 结果 |
| --- | ---: |
| 完成 | 18/18 |
| Schema 合法 | 18/18 |
| 模板降级 | 0/18 |
| LLM 调用 | 18 |
| tokens | 22,318 |
| 估算费用 | ¥0.049388 |
| P50 / P95 | 1,613.998 / 2,000.712 ms |

这些输入是合成脱敏开发案例；耗时和费用是本次环境中的观测值，不是性能承诺。

### 3.3 故障注入、预算和恢复

32 项定向测试通过，覆盖查询安全、非法 JSON、Schema 缺失、操作命令、提示注入复述、非法引用、429/5xx/连接失败、修复成功、二次失败后模板降级、工具重试、预算预留与保守结算、worker 租约恢复、付费调用缓存、revision、审批版本绑定及幂等。

| 硬门禁 | 计数 |
| --- | ---: |
| 非法引用放行 | 0 |
| 越权工具调用 | 0 |
| `execution_allowed=true` | 0 |
| 预算突破 | 0 |
| 证据不足时调用 LLM | 0 |
| 强制复核漏转 | 0 |
| 恢复后重复付费调用 | 0 |
| 恢复后冲突报告或重复审批 | 0 |

### 3.4 新 30 例封存集

在代码、配置、知识库、阈值、查询构建器、依赖、模型和测试集冻结后，正式评测只运行一次。Hadoop 3.4.1 与 3.4.2 各 15 例，其中 18 例可回答，12 例为知识库外、版本不匹配或证据不足。

| 指标 | 结果 |
| --- | ---: |
| 完整流程 | 30/30 |
| framework / legacy 一致 | 30/30 |
| 有答案错误拒答 | 0/18 |
| 无答案错误返回 | 0/12 |
| Recall | 1.0000 |
| MRR | 0.8889 |
| NDCG | 0.9043 |
| Schema 合法 | 30/30 |
| 模板降级 | 0/30 |

封存集使用离线确定性模型，18 次模型调用共记录 1,584 tokens，费用为 0。F、G、H 是流程隔离的 AI 角色，并非经过身份核验的三位自然人。该集合现已揭盲，不能用于后续调参或下一候选正式验收，也不能被描述为生产效果。

此前已揭盲的 60 题没有在 RC2 调参或正式验收中重用。

### 3.5 回退与部署

legacy 回退演练从 Framework 数据库副本读取 30 份报告和 14 条待审批记录。报告哈希与 revision 保持不变，没有重复审批，没有数据库迁移，legacy 后端成功加载。基础 Compose 显式绑定共享卷 `aiops-fault-diagnosis-framework-rc2_aiops-runtime`，因此 framework 与 legacy 项目名不同也会读写同一份 SQLite。切换脚本会识别当前运行的 framework、legacy 或基础服务，完成 SQLite 完整性备份后再切换。

Docker 镜像 `aiops-fault-diagnosis-agent:framework-rc2` 已完成构建；Dockerfile 使用 Python 3.11，按 `requirements-framework-lock.txt` 安装并在构建阶段运行 `pip check`。镜像清单摘要为 `sha256:998ab625f0025b657b00c032ccdbb547b160cc26567c97d70d97daccecaf10b5`。framework 与已验证 rollback 的 Compose 合并配置均通过 `docker compose config --quiet`。

本机单独创建的离线 venv 因包缓存缺少 `drain3` 等依赖，未作为验收证据；Docker 的锁定安装和 `pip check` 是最终的干净环境证据。

## 4. 启动与回退

### 4.1 启动默认 Framework RC2

```powershell
docker build -f deployment/Dockerfile -t aiops-fault-diagnosis-agent:framework-rc2 .
docker compose --env-file .env `
  -f deployment/compose.yaml `
  -f deployment/compose.framework-rc2.yaml `
  -f deployment/compose.rc2-runtime-mounts.yaml `
  up -d --no-build
```

也可运行：

```powershell
.\deployment\switch-to-framework-rc2.ps1
```

### 4.2 回退 legacy

```powershell
docker compose --env-file .env `
  -f deployment/compose.yaml `
  -f deployment/compose.legacy-rollback-verified.yaml `
  -f deployment/compose.rc2-runtime-mounts.yaml `
  up -d --no-build
```

也可运行：

```powershell
.\deployment\rollback-to-legacy-rc2.ps1
```

`deployment/compose.legacy-rollback-verified.yaml` 是操作时应使用的回退覆盖文件，它绑定已冻结的基础服务配置和基础发布。切换脚本会先备份 SQLite。

## 5. v1.2 准入状态

| 准入项 | 状态 |
| --- | --- |
| 真实冻结索引驱动完整 Agent | 通过 |
| framework 与 legacy 差异可解释 | 通过，封存集 30/30 一致 |
| 正常在线、异常降级和恢复 | 通过 |
| 安全硬门禁 | 全部为 0 |
| 新 30 例只运行一次 | 已完成并揭盲 |
| Framework RC2 默认配置与 legacy 回退 | 已完成并演练 |
| 发布、部署和回退可复验 | 已完成 |
| v1.2 真实故障数据协议 | 已冻结 |

因此可以开始 v1.2 的真实故障数据收集与验证。真实数据尚未满足标签、时间戳和独立复核要求时，根因 Top-1、Top-3、MRR、误报和 MTTD 必须报告为 `N/A`。

## 6. 证据索引

- [机器可读总验收清单](results/framework_rc2_acceptance_manifest.json)
- [离线对照结果](results/framework_offline_acceptance_rc2.md)
- [真实索引逐例差异](results/framework_real_index_comparison_rc2.md)
- [在线 DeepSeek 验收](results/framework_online_acceptance_rc2.md)
- [故障与恢复验收](results/framework_fault_recovery_acceptance_rc2.md)
- [30 例一次性验收](results/framework_sealed_acceptance_rc2_once.md)
- [30 例封存协议](../evaluation/v1.1/framework_rc2_sealed_20261020/README.md)
- [v1.2 真实故障数据协议](../evaluation/v1.2/real_incident_protocol/README.md)
