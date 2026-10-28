# 服务平台

## 模块职责

提供 FastAPI、worker、SQLite、Streamlit 和运行时装配。

## 依赖边界

作为最外层组合根依赖业务模块，业务模块不依赖本层。

## Python 文件说明

| 文件 | 主要功能 | 主要类或函数 |
| --- | --- | --- |
| `__init__.py` | 定义当前包的公共入口、版本或导出符号。 | — |
| `__main__.py` | 实现 `python -m` 命令行入口和参数分发。 | `main` |
| `api.py` | 创建 FastAPI 应用并定义 HTTP 接口。 | `ServiceError`、`_encode_cursor`、`_decode_cursor`、`_time_bound`、`_task`、`_diagnosis`、`_approval`、`create_app` |
| `benchmark.py` | 采集服务吞吐、延迟和资源使用指标。 | `_percentile`、`_meta`、`_sequences`、`e1`、`e2`、`e3`、`e4`、`run` |
| `config.py` | 读取、校验并规范化当前模块的 YAML 配置。 | `load` |
| `mcp_server.py` | 以 stdio JSON-RPC 暴露只读工具（MCP tools 能力）。 | `McpServer`、`ToolFacade` |
| `tracing.py` | 记录诊断链路的 trace/span 并写入 SQLite。 | `Tracer`、`Trace`、`SpanRecord` |
| `metrics_store.py` | 读取 CSV/JSONL 指标并按主机与时间窗聚合。 | `MetricsStore` |
| `db.py` | 管理 SQLite 任务、预算、报告、审批和审计记录。 | `IdempotencyConflict`、`QueueFull`、`LeaseLost`、`ApprovalConflict`、`ApprovalExpired`、`now`、`_deadline`、`Database` |
| `pipeline.py` | 连接服务请求、检测、检索与诊断流程。 | `BufferedWriter`、`_raw_rows`、`_parquet_rows`、`_host_alias`、`_stage_db`、`_session_rows`、`_score_sessions`、`_event_groups` 等 |
| `release.py` | 校验并生成当前模块的不可变发布清单。 | `_read`、`_w2_run`、`_components`、`_bundle_names`、`publish`、`verify`、`ReleaseMetadata`、`FrozenRelease` |
| `runtime.py` | 装配配置、数据库、发布制品和后台 worker。 | `ServiceRuntime` |
| `schemas.py` | 定义当前模块输入输出的 Pydantic 数据结构。 | `StrictModel`、`ErrorBody`、`RegisteredRequest`、`RegisteredBatchList`、`TaskResponse`、`BatchResponse`、`EventItem`、`EventList` 等 |
| `streamlit_app.py` | 实现供人工查看与复核的 Streamlit 页面。 | — |
| `ui_client.py` | 封装 Streamlit 调用 FastAPI 的客户端。 | `ApiClient` |

## 阅读建议

先阅读配置或 Schema，再阅读核心引擎，最后查看 `workflow.py`、`__main__.py` 或验收脚本了解完整调用顺序。文件内的中文注释重点解释职责、输入参数、数据字段和关键约束。
