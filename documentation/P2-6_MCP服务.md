# P2-6：MCP 服务实施报告

> 目标：把只读工具从"绑死在项目里"变成"任何 MCP 客户端都能调用"。
> 结果：一个零依赖的 stdio MCP 服务器，暴露 5 个只读工具，`initialize / tools/list / tools/call` 全链路冒烟通过。

---

## 1. 为什么做 MCP

原来的工具只能被本项目内部的 Agent 调用。MCP（Model Context Protocol）是 2025 年起被广泛支持的"工具接入协议"：客户端（Claude Desktop、Cursor 等）通过 `tools/list` 发现工具、通过 `tools/call` 调用工具。

把工具层做成 MCP 服务，等于回答面试里的一个问题：**"你的工具层能不能被别的 Agent 复用？"**

## 2. 实现

| 组件 | 功能 | 文件 |
| --- | --- | --- |
| MCP 服务器 | JSON-RPC over stdio，实现 initialize / tools/list / tools/call | `platform/mcp_server.py` |
| 工具门面 | 把 5 个只读工具适配成统一契约 | 同上 `ToolFacade` |
| Schema | 复用 `tool_specs`，调用前校验参数 | `diagnosis/tool_specs.py` |
| 冒烟脚本 | 子进程启动服务器并跑通三类请求 | `ops/scripts/mcp_smoke.py` |
| 单测 | 握手、清单、调用、非法工具、非法参数、通知 | `tests/test_mcp.py` |

暴露的工具（全部只读）：

| 工具 | 作用 |
| --- | --- |
| `detect_anomaly` | 读事件的异常分数、阈值与会话 |
| `query_logs` | 按事件读取脱敏日志（≤500 行） |
| `query_metrics` | 读事件时间窗内的指标序列 |
| `search_similar_incidents` | 检索历史已结案事件 |
| `read_trace_summary` | 读聚合调用链摘要 |

`retrieve_runbook` 没有暴露：它依赖冻结的检索制品，属于"部署相关"能力，强行塞进 MCP 会让服务启动依赖大文件。这是有意的取舍。

## 3. 只读保证

- 协议层只实现 `initialize`、`tools/list`、`tools/call`，没有 `resources/write`、`prompts` 等写能力；
- 工具门面只调用 `AgentTools` 的查询方法，没有任何执行入口；
- 参数先过 `validate_arguments`，非法参数直接返回 JSON-RPC 错误；
- 未知工具返回 `-32602`，未知方法返回 `-32601`。

## 4. 冒烟结果

```powershell
python ops/scripts/mcp_smoke.py
```

```json
{
  "server": {"name": "aiops-diag-readonly", "version": "1.0"},
  "tools": ["detect_anomaly", "query_logs", "query_metrics",
            "search_similar_incidents", "read_trace_summary"],
  "read_only": true,
  "call": {"isError": false, "event": "evt_9658...", "ok": true}
}
```

## 5. 接入方式

```json
{
  "mcpServers": {
    "aiops-diag": {
      "command": "python",
      "args": ["-m", "aiops_diag.platform.mcp_server",
               "--database", "/abs/path/service.sqlite3",
               "--metrics", "/abs/path/metrics.csv"],
      "env": {"PYTHONPATH": "/abs/path/src"}
    }
  }
}
```

## 6. 局限

- 只支持 stdio，没有 SSE / HTTP 传输；
- 没有鉴权，默认假设本地单用户使用；
- 没有实现 `resources` 与 `prompts` 能力，只做工具；
- 大结果集未分页，`query_logs` 上限 500 行。

## 7. 面试可以这样讲

1. "我的工具层不绑死在本项目里：它同时是一个 MCP 服务器，Claude Desktop 或 Cursor 可以直接发现并调用这 5 个只读工具。"
2. "协议层只实现了 tools 能力，没有任何写方法；参数先过 JSON Schema，未知工具直接拒绝。"
3. "这是零依赖实现——没装 MCP SDK，用 JSON-RPC over stdio 把协议跑通，也顺手验证了我对协议本身的理解。"
