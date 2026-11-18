"""验证 MCP 服务器的初始化、工具清单与只读调用。"""

import json

from aiops_diag.platform.db import Database
from aiops_diag.platform.mcp_server import McpServer, ToolFacade


# _database 构造带一条事件的最小数据库。
def _database(tmp_path):
    database = Database(tmp_path / "service.sqlite3")
    database.init()
    with database.transaction() as raw:
        raw.execute(
            "INSERT INTO batches(batch_id,source_kind,source_ref,input_hash,release_id,"
            "processing_hash,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            ("bat_1", "upload", "x", "h", "r", "p", "SUCCEEDED",
             "2020-01-01T00:00:00+00:00", "2020-01-01T00:00:00+00:00"))
        raw.execute(
            "INSERT INTO events(event_id,batch_id,host_alias,start_time,end_time,detected_at,"
            "max_anomaly_score,threshold,session_count,status) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("evt_1", "bat_1", "h1", "2020-01-01T00:00:00+00:00",
             "2020-01-01T00:01:00+00:00", "2020-01-01T00:01:00+00:00", 2.0, 1.0, 1,
             "ANOMALY_DETECTED"))
    return database


# test_mcp_initialize_and_list 验证握手与工具清单。
def test_mcp_initialize_and_list(tmp_path):
    server = McpServer(ToolFacade(_database(tmp_path)))
    init = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert init["result"]["protocolVersion"]
    tools = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {item["name"] for item in tools["result"]["tools"]}
    assert names == {"detect_anomaly", "query_logs", "query_metrics",
                     "search_similar_incidents"}


# test_mcp_call_returns_text_and_rejects_bad_input 验证调用与参数校验。
def test_mcp_call_returns_text_and_rejects_bad_input(tmp_path):
    server = McpServer(ToolFacade(_database(tmp_path)))
    call = server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                          "params": {"name": "detect_anomaly",
                                     "arguments": {"event_id": "evt_1"}}})
    assert call["result"]["isError"] is False
    assert json.loads(call["result"]["content"][0]["text"])["ok"] is True
    unknown = server.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                             "params": {"name": "shell", "arguments": {}}})
    assert unknown["error"]["code"] == -32602
    invalid = server.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                             "params": {"name": "query_metrics", "arguments": {}}})
    assert invalid["error"]["code"] == -32602


# test_mcp_query_metrics_reads_csv 验证指标文件可通过 MCP 查询。
def test_mcp_query_metrics_reads_csv(tmp_path):
    metrics = tmp_path / "metrics.csv"
    metrics.write_text(
        "timestamp,host_alias,component,metric,value\n"
        "2020-01-01T00:00:30+00:00,h1,DataNode,disk_used_ratio,0.99\n", encoding="utf-8")
    server = McpServer(ToolFacade(_database(tmp_path), str(metrics)))
    call = server.handle({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                          "params": {"name": "query_metrics",
                                     "arguments": {"event_id": "evt_1"}}})
    payload = json.loads(call["result"]["content"][0]["text"])
    assert payload["data"]["status"] == "available"


# test_mcp_notification_is_ignored 验证通知类消息不产生响应。
def test_mcp_notification_is_ignored(tmp_path):
    server = McpServer(ToolFacade(_database(tmp_path)))
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
