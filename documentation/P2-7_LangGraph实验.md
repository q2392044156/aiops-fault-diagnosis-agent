# P2-7 LangGraph 实验：能力与 5 例 WSL PoC

> 目标：验证 LangGraph 后端能否接入真实故障实验链路，并给出可复现的 5 例结果。
> 结论先行：**能跑通，5 例 Top-1 4/5；它与主引擎不是同一条代码路径，不能直接对比 WSL 的 98.5%。**

## 1. LangGraph 在项目中的定位

| 项 | 说明 |
| --- | --- |
| 角色 | 第二套**可选执行后端** |
| 默认 | 否；主路径是自研 7 节点状态机 |
| 开关 | `agent_backend: framework_candidate` + `execution_backend: langgraph` |
| 依赖 | `langgraph==1.2.16`、`langchain-core==1.6.12`（可选组 `framework`） |
| 适用 | 框架对照、v1.2 RC 验收、面试演示 |

## 2. 已实现能力

| 能力 | 文件 | 说明 |
| --- | --- | --- |
| 7 节点状态图 | `framework/graph.py` | 业务节点映射为图节点 |
| 条件路由 | `framework/graph.py` | 按持久化 `current_node` 选择下一节点 |
| 单步推进 | `framework/graph.py` | 每次调用只走一个节点，然后 END |
| 让出/恢复 | `framework/graph.py` | 捕获 `AgentYield`，写回让出节点 |
| SQLite checkpoint | `framework/checkpoint.py` | `get_tuple/put/list/delete`，thread = release:diagnosis:revision |
| v1.2 工具 | `framework/tools_v12.py` | 只读工具扩展点（Trace 已移除） |
| LangChain 检索适配 | `framework/retriever.py` | 保留 release 元数据、空结果 fail-closed |
| LangChain 报告链 | `framework/report_chain.py` | 结构化摘要、审计回调、降级 |
| 发布校验 | `framework/release_v12.py` | 冻结/校验 v1.2 清单 |
| 评测与验收 | `framework/evaluation.py`、`ops/scripts/run_framework_*` | 对照、封存、恢复演练 |
| 测试 | `tests/test_framework_v12.py` | 图、checkpoint、报告链、发布锁 |

设计要点：**图只负责下一步走哪个节点，业务状态仍以 SQLite 业务表为准**。

## 3. 接入实验链路

新增 `ops/lab/harness/ingest.py --agent-backend langgraph`：

- 构造 `LangGraphAgent`，而不是原生 `Agent`；
- 注入 `v12.enabled=True`、`execution_backend=langgraph`、`query_builder` 配置；
- 复用 `CardRetriever` 与 `OfflineClient`；
- 默认 `native` 不变，原有实验不受影响。

## 4. 5 例 WSL PoC

### 4.1 设置

- 案例：2 例卷故障、2 例心跳、1 例安全模式；
- 后端：LangGraph；
- 数据库：`runtime/lab/langgraph_poc.sqlite3`；
- 案例副本：`runtime/lab/langgraph_poc_cases`（不改动原数据）。

命令：

```powershell
python ops/lab/harness/langgraph_poc.py
```

### 4.2 结果

| 案例 | 期望 | 候选前三 | Top-1 |
| --- | --- | --- | --- |
| evt_ec434c344967c8 | DN_VOLUME | DN_VOLUME, NN_SAFE_MODE, NN_AVAILABILITY | ✅ |
| evt_2ec435f1c93a15 | DN_VOLUME | DN_VOLUME, NN_SAFE_MODE, NN_AVAILABILITY | ✅ |
| evt_0ab71a36a43d77 | DN_HEARTBEAT | DN_HEARTBEAT, DN_VOLUME, BLOCK_REPORT | ✅ |
| evt_24e798915f7726 | DN_HEARTBEAT | DN_VOLUME, DN_HEARTBEAT, BLOCK_REPORT | ❌ |
| evt_2dd8715b1f58de | NN_SAFE_MODE | NN_SAFE_MODE | ✅ |

**Top-1 4/5；checkpoint 写入 90 条**（每次诊断约 18 个图步骤）。

### 4.3 失败分析

失败的心跳案例日志里：

- `lost heartbeat / removedead / dead datanode` 均为 0；
- `heartbeat` 仅 2 次，`volume` 10 次。

LangGraph 走的是 v1.1 候选路径 `CandidateAgent`：

- 检索计划由 `query_builder` 生成；
- 证据没有经过主引擎的"信号行优先"选择；
- 排序时弱先验把 `volume` 排在 `heartbeat` 前面。

因此这不是 LangGraph 本身的问题，而是**两条引擎路径的证据处理不一致**。

## 5. 与主引擎的关系

| 维度 | 主引擎 | LangGraph 后端 |
| --- | --- | --- |
| 代码路径 | `diagnosis/agent.py` | `v11/candidate.py` + 图包装 |
| 证据选择 | 信号行优先 + 弱先验 | query_builder + 原始窗口 |
| 状态 | 业务表 | 业务表 + checkpoint |
| 默认 | ✅ | ❌ |
| 当前结果 | WSL 67/68 | 5 例 4/5（样本不同，不可直接比） |

## 6. 限制与下一步

1. 目前只做了 5 例 PoC，**不能**据此声称 LangGraph 达到 67/68；
2. 若要全量跑 68 + 81，需要把主引擎的"信号行优先 + 弱先验"移植到 candidate 路径；
3. 移植后要重新评测，不能假设数字不变；
4. 面试表述建议：

> "LangGraph 我接了可选后端，并用 5 例 WSL 验证能跑通：4/5 Top-1、90 条 checkpoint。它和主引擎不是同一条路径，所以我不会把两者的数字混在一起报。"

## 7. 相关文件

- `src/online/diagnosis/framework/graph.py`
- `src/online/diagnosis/framework/checkpoint.py`
- `ops/lab/harness/ingest.py`
- `ops/lab/harness/langgraph_poc.py`
- `tests/test_framework_v12.py`
