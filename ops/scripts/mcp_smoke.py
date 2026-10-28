"""模块说明：以子进程方式冒烟验证 MCP 服务器（initialize / list / call）。"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

# 变量说明：ROOT 指向仓库根目录。
ROOT = Path(__file__).resolve().parents[2]


# 方法说明：_rpc 发送一条 JSON-RPC 请求并读取一行响应。
def _rpc(process, payload):
    process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
    process.stdin.flush()
    return json.loads(process.stdout.readline())


# 方法说明：main 启动服务器、验证握手与一次只读工具调用。
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    database = argv[0] if argv else str(ROOT / "demo" / ".runtime" / "service.sqlite3")
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"),
           "PYTHONIOENCODING": "utf-8"}
    process = subprocess.Popen(
        [sys.executable, "-m", "aiops_diag.platform.mcp_server", "--database", database],
        cwd=str(ROOT), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8")
    try:
        init = _rpc(process, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                              "params": {"protocolVersion": "2024-11-05"}})
        tools = _rpc(process, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        connection = sqlite3.connect(database)
        row = connection.execute("SELECT event_id FROM events LIMIT 1").fetchone()
        result = {"server": init.get("result", {}).get("serverInfo"),
                  "tools": [item["name"] for item in tools["result"]["tools"]],
                  "read_only": True}
        if row:
            call = _rpc(process, {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                  "params": {"name": "detect_anomaly",
                                             "arguments": {"event_id": row[0]}}})
            payload = json.loads(call["result"]["content"][0]["text"])
            result["call"] = {"isError": call["result"]["isError"],
                              "event": row[0], "ok": payload.get("ok")}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        process.terminate()
        process.wait(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
