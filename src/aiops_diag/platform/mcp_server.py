"""模块说明：把只读工具暴露为 MCP 服务器（stdio JSON-RPC）。"""

from __future__ import annotations

import argparse
import json
import sys

from aiops_diag.diagnosis.tool_specs import TOOL_SPECS, validate_arguments
from aiops_diag.diagnosis.tools import AgentTools, result
from aiops_diag.platform.db import Database

# 变量说明：PROTOCOL 是服务器声明的 MCP 协议版本。
PROTOCOL = "2024-11-05"
# 变量说明：TOOL_NAMES 是允许通过 MCP 暴露的只读工具。
TOOL_NAMES = ("detect_anomaly", "query_logs", "query_metrics",
              "search_similar_incidents", "read_trace_summary")


# 类说明：ToolFacade 把 MCP 调用适配到现有只读工具，不提供任何写操作。
class ToolFacade:
    # 方法说明：__init__ 装配只读工具，缺少检索制品时不影响其余工具。
    def __init__(self, database, metrics_path=None):
        self.db = database
        self.tools = AgentTools(database, {"tools": {"metrics_path": metrics_path}},
                                None, {"release_id": "mcp-readonly",
                                       "model_id": "not_available", "threshold": 1.0})

    # 方法说明：call 按工具名分发，返回统一的结果契约。
    def call(self, name, arguments):
        event_id = arguments.get("event_id")
        if name == "detect_anomaly":
            return self.tools.detect_anomaly(event_id)
        if name == "query_logs":
            return self.tools.query_logs(event_id, int(arguments.get("limit", 50)))
        if name == "query_metrics":
            return self.tools.query_metrics(event_id)
        if name == "search_similar_incidents":
            event = self.db.one("SELECT * FROM events WHERE event_id=?", (event_id,))
            if not event:
                return result(error={"code": "EVENT_NOT_FOUND",
                                     "message": "Event was not found", "retryable": False})
            return self.tools.search_similar_incidents(
                "", event, "", int(arguments.get("top_k", 5)))
        if name == "read_trace_summary":
            row = self.db.one("SELECT * FROM event_trace_evidence WHERE event_id=?",
                              (event_id,))
            if not row:
                return result({"status": "not_available", "item": None},
                              provenance={"event_id": event_id})
            return result({"status": "available", "item": {
                "event_id": event_id,
                "summary": json.loads(row["summary_json"]),
                "evidence_hash": row["evidence_hash"],
                "source_version": row["source_version"],
                "observed_at": row["observed_at"],
                "observed_until": row["observed_until"]}},
                provenance={"event_id": event_id, "source": "event_trace_evidence"})
        raise ValueError(f"Unknown tool: {name}")


# 类说明：McpServer 处理 JSON-RPC 请求，只实现 MCP 的 tools 能力。
class McpServer:
    # 方法说明：__init__ 保存工具门面。
    def __init__(self, facade):
        self.facade = facade

    # 方法说明：tools 返回 MCP 工具清单（名称、描述、输入 Schema）。
    @staticmethod
    def tools():
        return [{"name": name, "description": TOOL_SPECS[name]["description"],
                 "inputSchema": TOOL_SPECS[name]["parameters"]} for name in TOOL_NAMES]

    # 方法说明：handle 处理一条 JSON-RPC 请求，通知类消息返回 None。
    def handle(self, request):
        method = request.get("method")
        request_id = request.get("id")
        if request_id is None:
            return None
        try:
            if method == "initialize":
                value = {"protocolVersion": PROTOCOL,
                         "capabilities": {"tools": {"listChanged": False}},
                         "serverInfo": {"name": "aiops-diag-readonly", "version": "1.0"}}
            elif method == "tools/list":
                value = {"tools": self.tools()}
            elif method == "tools/call":
                params = request.get("params") or {}
                name = params.get("name")
                arguments = params.get("arguments") or {}
                if name not in TOOL_NAMES:
                    raise ValueError(f"Unknown tool: {name}")
                errors = validate_arguments(name, arguments)
                if errors:
                    raise ValueError("; ".join(errors))
                output = self.facade.call(name, arguments)
                value = {"content": [{"type": "text", "text": json.dumps(
                    output, ensure_ascii=False)}],
                    "isError": not bool(output.get("ok", True))}
            else:
                return {"jsonrpc": "2.0", "id": request_id,
                        "error": {"code": -32601, "message": f"Method not found: {method}"}}
            return {"jsonrpc": "2.0", "id": request_id, "result": value}
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": request_id,
                    "error": {"code": -32602, "message": str(exc)[:300]}}

    # 方法说明：serve 逐行读取 stdin 并写出 stdout，直到输入结束。
    def serve(self, stdin, stdout):
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                response = {"jsonrpc": "2.0", "id": None,
                            "error": {"code": -32700, "message": "Parse error"}}
            else:
                response = self.handle(request)
            if response is not None:
                stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                stdout.flush()


# 方法说明：main 启动 stdio MCP 服务器。
def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only AIOps MCP server")
    parser.add_argument("--database", required=True)
    parser.add_argument("--metrics", default=None)
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    database = Database(args.database)
    McpServer(ToolFacade(database, args.metrics)).serve(sys.stdin, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
