# 诊断包

## 模块职责

执行只读诊断、预算控制与报告校验；v1.1 候选链路在 `candidate.py`，LangGraph 封装在 `framework/`。

## 依赖边界

不导入采集、检索与检索评测层的实现；检索只经 `online.knowledge` 的公开入口。

## Python 文件说明

| 文件 | 主要职责 | 主要接口 |
| --- | --- | --- |
| `__init__.py` | 定义当前包的公开入口与版本号导出。 | — |
| `__main__.py` | 实现 `python -m` 的发布、校验与复核员初始化子命令。 | `main` |
| `agent.py` | 按 7 个持久化节点推进诊断，调用只读工具并产出候选报告；`AgentYield` 负责交还执行权。 | `AgentYield`、`utcnow`、`Agent` |
| `auth.py` | 校验复核员身份、角色与令牌指纹。 | `ReviewerAuthError`、`token_hash`、`ReviewerRegistry`、`initialize_reviewer` |
| `budget.py` | 预算账本读写并拦截模型调用预算。 | `DatabaseBudgetLedger` |
| `candidate.py` | v1.1 候选 Agent：在持久化节点链上叠加候选门禁，并校验报告摘要。 | `CandidateAgent`、`CandidateSummary` |
| `context_builder.py` | 按 token 预算装配上下文，支持全量/压缩/最小三档。 | `build_context`、`estimate_tokens`、`STRATEGIES` |
| `evidence.py` | 结构化证据选择、标签去重与充分性判断。 | `EvidenceSelector`、`WEAK_TERMS` |
| `isolation.py` | 定义评测用例集契约，并校验 adev 与 atest 互不重叠。 | `COMPOSITIONS`、`load_cases`、`validate_isolation` |
| `release.py` | 校验并生成 v1.0 身份清单（源码哈希、依赖与部署描述）。 | `code_hashes`、`publish`、`verify` |
| `release_candidate.py` | 校验并生成候选身份清单（源码哈希、依赖、部署与查询构造器）。 | `publish`、`verify` |
| `retrieval_query.py` | 为 v1.1 RC2 生成确定性检索查询。 | `RetrievalQueryBuilder`、`load_config` |
| `tool_router.py` | 实现受控工具的路由，并做参数 Schema 校验与兜底。 | `ToolRouter`、`TOOL_ROUTER_PROMPT` |
| `schemas.py` | 定义诊断包对外输出的 Pydantic 数据结构。 | `StrictModel`、`ToolResult`、`Evidence`、`Hypothesis`、`ActionAdvice`、`GeneratedReportBody`、`IncidentReport`、`RouterDecision` |
| `settings.py` | 读取本包配置：预算上限、工具开关与数据路径。 | `load` |
| `signals.py` | 用可解释的权重和层级系数识别异常信号。 | `SIGNAL_RULES`、`analyze_row`、`analyze_rows`、`rank_codes` |
| `tool_specs.py` | 定义只读工具的 JSON Schema 与参数校验。 | `TOOL_SPECS`、`specs_for`、`validate_arguments` |
| `tools.py` | 实现只读工具包（日志查询、指标查询、runbook 检索与证据登记）。 | `result`、`AgentTools`、`CandidateAgentTools`、`log_evidence`、`document_evidence` |

## 阅读建议

先读 `schemas.py` 和 `tool_specs.py`，弄清一次报告与一次工具调用的形状；再看 `agent.py` 怎么按节点推进，`candidate.py` 在此基础上加了什么门禁；`evidence.py` 与 `signals.py` 解释证据从哪来。评测编排不在本包，见 `src/evaluation/agent/`。
