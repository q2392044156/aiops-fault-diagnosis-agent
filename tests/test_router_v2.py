"""模块说明：验证受控工具路由、工具 Schema、指标仓库与工具调用客户端。"""

import json

import httpx
import pytest

from aiops_diag.diagnosis.engine import AgentEngine
from aiops_diag.diagnosis.router_v2 import ToolRouter
from aiops_diag.diagnosis.tool_specs import specs_for, validate_arguments
from aiops_diag.diagnosis.tools import AgentTools
from aiops_diag.knowledge.generation.client import (BudgetLedger, DeepSeekClient,
                                                    DeepSeekError)
from aiops_diag.platform.metrics_store import MetricsStore


# 变量说明：METRICS_CSV 是测试用的两行指标样本。
METRICS_CSV = (
    "timestamp,host_alias,component,metric,value\n"
    "2020-01-01T00:00:00+00:00,h1,DataNode,disk_used_ratio,0.91\n"
    "2020-01-01T00:01:00+00:00,h1,DataNode,disk_used_ratio,0.99\n"
    "2020-01-01T00:02:00+00:00,h2,DataNode,disk_used_ratio,0.50\n"
)


# 方法说明：_invoke 构造一个直接返回固定工具调用的假调用器。
def _invoke(calls):
    # 方法说明：inner 模拟一次返回固定工具调用的模型响应。
    def inner(messages, tools):
        return calls, {"input_tokens": 10, "output_tokens": 5, "estimated_cost_cny": 0.0}
    return inner


# 方法说明：test_specs_expose_function_definitions 确认工具定义符合 function calling 结构。
def test_specs_expose_function_definitions():
    specs = specs_for(["query_metrics"])
    assert specs[0]["type"] == "function"
    assert specs[0]["function"]["name"] == "query_metrics"
    assert specs[0]["function"]["parameters"]["additionalProperties"] is False


# 方法说明：test_schema_rejects_invalid_arguments 覆盖缺失、越界与非法字段。
def test_schema_rejects_invalid_arguments():
    assert validate_arguments("query_metrics", {"event_id": "evt_1"}) == []
    assert "missing required field" in " ".join(validate_arguments("query_metrics", {}))
    assert "does not match pattern" in " ".join(
        validate_arguments("query_metrics", {"event_id": "bad"}))
    assert "unexpected field" in " ".join(
        validate_arguments("query_metrics", {"event_id": "evt_1", "extra": 1}))
    assert validate_arguments("unknown_tool", {}) == ["unknown tool"]


# 方法说明：test_router_keeps_allowed_blocks_unknown_and_bad_json 验证白名单与参数校验。
def test_router_keeps_allowed_blocks_unknown_and_bad_json():
    calls = [
        {"name": "query_metrics", "arguments": json.dumps({"event_id": "evt_1"})},
        {"name": "shell", "arguments": "{}"},
        {"name": "query_metrics", "arguments": "not-json"},
    ]
    out = ToolRouter(["query_metrics", "search_similar_incidents"]).route({}, _invoke(calls))
    assert out["names"] == ["query_metrics"]
    reasons = {item["reason"] for item in out["blocked"]}
    assert {"tool_not_allowed", "invalid_json"} <= reasons
    assert out["policy"] == "model"


# 方法说明：test_router_dedupes_and_caps_tools 验证去重、优先级排序与数量上限。
def test_router_dedupes_and_caps_tools():
    calls = [
        {"name": "search_similar_incidents", "arguments": json.dumps({"event_id": "evt_1"})},
        {"name": "query_metrics", "arguments": json.dumps({"event_id": "evt_1"})},
        {"name": "query_metrics", "arguments": json.dumps({"event_id": "evt_1"})},
    ]
    out = ToolRouter(["query_metrics", "search_similar_incidents"],
                     max_tools=1).route({}, _invoke(calls))
    assert out["names"] == ["query_metrics"]
    assert any(item["reason"] == "duplicate" for item in out["blocked"])


# 方法说明：test_router_falls_back_on_error 确认路由异常不会中断诊断。
def test_router_falls_back_on_error():
    # 方法说明：boom 模拟模型调用超时，用于验证回落路径。
    def boom(messages, tools):
        raise TimeoutError("slow")
    out = ToolRouter(["query_metrics"]).route({}, boom)
    assert out["names"] == [] and out["policy"] == "fallback"


# 方法说明：test_router_returns_none_when_model_chooses_nothing 确认空选择是合法结果。
def test_router_returns_none_when_model_chooses_nothing():
    out = ToolRouter(["query_metrics"]).route({}, _invoke([]))
    assert out["names"] == [] and out["policy"] == "none" and out["blocked"] == []


# 方法说明：test_metrics_store_window_and_stats 验证时间窗过滤与统计值。
def test_metrics_store_window_and_stats(tmp_path):
    path = tmp_path / "metrics.csv"
    path.write_text(METRICS_CSV, encoding="utf-8")
    store = MetricsStore(path)
    series = store.window("h1", "2020-01-01T00:00:00+00:00", "2020-01-01T00:01:30+00:00")
    assert len(series) == 1
    assert series[0]["count"] == 2
    assert series[0]["max"] == 0.99
    assert store.window("h2", "2020-01-01T04:00:00+00:00", "2020-01-01T04:00:30+00:00") == []


# 方法说明：test_query_metrics_returns_real_series 确认工具在有指标文件时返回 available。
def test_query_metrics_returns_real_series(tmp_path):
    # 类说明：Database 提供查询事件所需的只读桩。
    class Database:
        # 方法说明：one 返回固定的事件行。
        def one(self, query, params=()):
            return {"event_id": "evt_1", "host_alias": "h1",
                    "start_time": "2020-01-01T00:00:00+00:00",
                    "end_time": "2020-01-01T00:01:00+00:00"}

    path = tmp_path / "metrics.csv"
    path.write_text(METRICS_CSV, encoding="utf-8")
    tools = AgentTools(Database(), {"tools": {"metrics_path": str(path)}}, None,
                       {"release_id": "demo"})
    value = tools.query_metrics("evt_1")
    assert value["ok"] is True
    assert value["data"]["status"] == "available"
    assert value["data"]["series"][0]["metric"] == "disk_used_ratio"


# 方法说明：test_query_metrics_stays_unavailable_without_store 确认缺少指标时保持原语义。
def test_query_metrics_stays_unavailable_without_store():
    # 类说明：Database 提供查询事件所需的只读桩。
    class Database:
        # 方法说明：one 返回固定的事件行。
        def one(self, query, params=()):
            return {"event_id": "evt_1", "host_alias": "h1",
                    "start_time": "2020-01-01T00:00:00+00:00",
                    "end_time": "2020-01-01T00:01:00+00:00"}

    value = AgentTools(Database(), {"tools": {}}, None, {"release_id": "demo"}).query_metrics("evt_1")
    assert value["data"]["status"] == "not_available"


# 方法说明：test_client_parses_tool_calls 用 MockTransport 验证 function calling 解析与计费。
def test_client_parses_tool_calls(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")

    # 方法说明：handler 返回一个固定的 function calling 响应。
    def handler(request):
        return httpx.Response(200, json={
            "choices": [{"message": {"tool_calls": [{
                "id": "call_1", "type": "function",
                "function": {"name": "query_metrics",
                             "arguments": "{\"event_id\": \"evt_1\"}"}}]}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 6},
        })

    budget = {"max_total_tokens": 1000, "max_cost_cny": 1.0,
              "input_cny_per_million": 2.0, "output_cny_per_million": 8.0}
    cfg = {"provider": {"api_key_env": "DEEPSEEK_API_KEY",
                        "api_key_file_env": "DEEPSEEK_API_KEY_FILE",
                        "tracking_id_env": "DEEPSEEK_TRACKING_ID",
                        "tracking_id_file_env": "DEEPSEEK_TRACKING_ID_FILE",
                        "base_url": "https://api.deepseek.com", "model": "deepseek-flash",
                        "timeout_seconds": 5, "overall_timeout_seconds": 10,
                        "max_tokens": 100, "temperature": 0},
           "budget": budget, "paths": {}}
    ledger = BudgetLedger(tmp_path / "budget.json", budget)
    client = DeepSeekClient(cfg, transport=httpx.MockTransport(handler), ledger=ledger)
    calls, usage = client.complete_tool_calls([{"role": "user", "content": "hi"}],
                                              specs_for(["query_metrics"]))
    assert calls[0]["name"] == "query_metrics"
    assert json.loads(calls[0]["arguments"]) == {"event_id": "evt_1"}
    assert usage["input_tokens"] == 12 and usage["output_tokens"] == 6
    assert ledger.read()["calls"] == 1

# 类说明：StubClient 返回预设工具调用，用于验证引擎层的路由与预算。
class StubClient:
    # 变量说明：configured 表示该桩客户端被视为已配置。
    configured = True

    # 方法说明：__init__ 保存预设调用并初始化计数。
    def __init__(self, calls):
        self.calls = calls
        self.invocations = 0

    # 方法说明：complete_tool_calls 返回预设调用并累计调用次数。
    def complete_tool_calls(self, messages, tools):
        self.invocations += 1
        return list(self.calls), {"input_tokens": 10, "output_tokens": 5,
                                  "estimated_cost_cny": 0.0}


# 方法说明：_budget 构造引擎单次诊断所需的最小预算字典。
def _budget(max_llm_calls=3):
    return {"llm_calls": 0, "tokens": 0, "active_ms": 0, "estimated_cost_cny": 0.0,
            "max_llm_calls": max_llm_calls, "max_tokens": 12000, "max_active_ms": 120000,
            "max_tool_calls": 8, "tool_calls": 0}


# 方法说明：test_engine_route_v2_records_policy_and_blocks 验证引擎层 v2 路由的行为。
def test_engine_route_v2_records_policy_and_blocks():
    engine = AgentEngine.__new__(AgentEngine)
    engine.cfg = {"workflow": {"optional_router_version": "v2"}, "v12": {"enabled": False}}
    engine.client = StubClient([
        {"name": "query_metrics", "arguments": '{"event_id": "evt_1"}'},
        {"name": "shell", "arguments": "{}"},
    ])
    state = {"errors": [], "review_reasons": [], "tool_calls": [], "evidence_ids": []}
    budget = _budget()
    names = engine._route_v2(None, state, budget, {"event_id": "evt_1"})
    assert names == ["query_metrics"]
    assert state["router"]["policy"] == "model"
    assert state["router"]["blocked"][0]["reason"] == "tool_not_allowed"
    assert budget["llm_calls"] == 1 and budget["tokens"] == 15


# 方法说明：test_engine_llm_tools_enforces_call_budget 验证工具调用也受 LLM 预算约束。
def test_engine_llm_tools_enforces_call_budget():
    engine = AgentEngine.__new__(AgentEngine)
    engine.client = StubClient([])
    budget = _budget(max_llm_calls=1)
    engine._llm_tools(budget, [], [])
    with pytest.raises(DeepSeekError):
        engine._llm_tools(budget, [], [])
