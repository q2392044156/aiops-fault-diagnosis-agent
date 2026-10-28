"""模块说明：定义只读工具的 JSON Schema，供受控工具调用路由使用。"""

from __future__ import annotations

import re


# 变量说明：EVENT_ID 是事件编号的合法形式。
EVENT_ID = re.compile(r"^evt_[A-Za-z0-9_-]{1,64}$")

# 变量说明：TOOL_SPECS 是 OpenAI 风格的工具定义，name 与 AgentTools 方法一一对应。
TOOL_SPECS = {
    "query_metrics": {
        "name": "query_metrics",
        "description": "查询该事件时间窗内的指标序列（磁盘使用率、CPU、网络延迟等），"
                       "用于判断是否存在资源或网络层面的异常。",
        "parameters": {
            "type": "object",
            "properties": {"event_id": {"type": "string", "pattern": EVENT_ID.pattern}},
            "required": ["event_id"],
            "additionalProperties": False,
        },
    },
    "search_similar_incidents": {
        "name": "search_similar_incidents",
        "description": "检索同一组件下已结案的历史事件，用于识别复发模式；"
                       "只会返回观测时间早于当前事件的历史报告。",
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "pattern": EVENT_ID.pattern},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 10},
            },
            "required": ["event_id"],
            "additionalProperties": False,
        },
    },
    "read_trace_summary": {
        "name": "read_trace_summary",
        "description": "读取该事件的聚合调用链摘要（任务数、失败数、组件分布），"
                       "不返回原始 trace。仅当事件带 trace 证据时可用。",
        "parameters": {
            "type": "object",
            "properties": {"event_id": {"type": "string", "pattern": EVENT_ID.pattern}},
            "required": ["event_id"],
            "additionalProperties": False,
        },
    },
}

# 变量说明：PRIORITY 决定超预算时的保留顺序。
PRIORITY = ("query_metrics", "read_trace_summary", "search_similar_incidents")


# 方法说明：specs_for 把工具名转换为 function-calling 所需的定义列表。
def specs_for(names):
    return [{"type": "function", "function": dict(TOOL_SPECS[name])}
            for name in names if name in TOOL_SPECS]


# 方法说明：validate_arguments 按 JSON Schema 子集校验参数，返回错误列表。
def validate_arguments(name, arguments):
    spec = TOOL_SPECS.get(name)
    if spec is None:
        return ["unknown tool"]
    if not isinstance(arguments, dict):
        return ["arguments must be an object"]
    schema = spec["parameters"]
    errors = []
    for field in schema.get("required", []):
        if field not in arguments:
            errors.append(f"missing required field: {field}")
    properties = schema.get("properties", {})
    for field, value in arguments.items():
        if field not in properties:
            if schema.get("additionalProperties") is False:
                errors.append(f"unexpected field: {field}")
            continue
        rule = properties[field]
        if rule.get("type") == "string":
            if not isinstance(value, str):
                errors.append(f"{field} must be a string")
            elif rule.get("pattern") and not re.fullmatch(rule["pattern"], value):
                errors.append(f"{field} does not match pattern")
        elif rule.get("type") == "integer":
            if not isinstance(value, int) or isinstance(value, bool):
                errors.append(f"{field} must be an integer")
            elif "minimum" in rule and value < rule["minimum"]:
                errors.append(f"{field} below minimum")
            elif "maximum" in rule and value > rule["maximum"]:
                errors.append(f"{field} above maximum")
    return errors
