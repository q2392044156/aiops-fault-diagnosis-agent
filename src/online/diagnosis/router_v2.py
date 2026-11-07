"""模块说明：实现受控工具调用路由（function calling + 白名单 + 参数校验 + 回落）。"""

from __future__ import annotations

import json
import time

from .tool_specs import PRIORITY, specs_for, validate_arguments


# 变量说明：ROUTER_V2_PROMPT 是受控路由的系统提示，强调“信息足够就不要调用”。
ROUTER_V2_PROMPT = """你是只读诊断系统的工具路由器。你只能从提供的工具中选择，最多选择 {max_tools} 个。
按以下规则判断：
1. query_metrics：仅当 metrics_available=true 且（log_count<50 或组件属于 DataNode/NameNode/JournalNode/FSNamesystem）。
2. search_similar_incidents：仅当 historical_reports_available=true 且 recurring_pattern=true。
3. 若命中多个，按 query_metrics > search_similar_incidents 的顺序保留前 {max_tools} 个。
4. 没有命中时不要调用任何工具；空选择是合法答案。
"""


# 方法说明：_unpack 把模型返回的工具调用拆成名称与参数字典，失败时记录原因。
def _unpack(call):
    name = str(call.get("name") or "").strip()
    raw = call.get("arguments")
    try:
        arguments = json.loads(raw) if isinstance(raw, str) else dict(raw or {})
    except (ValueError, TypeError):
        return name, None, "invalid_json"
    if not isinstance(arguments, dict):
        return name, None, "arguments_not_object"
    return name, arguments, None


# 类说明：ToolRouter 把“模型选工具”限制在白名单、参数 Schema 和调用预算内。
class ToolRouter:
    """受控工具路由：模型只负责选择，是否允许、参数是否合法由程序判定。

    任何异常都会回落为空选择，保证诊断流程不因路由失败而中断。
    """

    # 方法说明：__init__ 按优先级稳定排序白名单，并记录单次最多可选工具数。
    def __init__(self, allowlist, max_tools=2):
        ordered = [name for name in PRIORITY if name in set(allowlist)]
        ordered += [name for name in allowlist if name not in ordered]
        self.allowlist = tuple(ordered)
        self.max_tools = max(1, int(max_tools))

    # 方法说明：route 调用模型并返回通过校验的工具选择、被拦截项与用量。
    def route(self, summary, invoke):
        started = time.perf_counter()
        messages = [
            {"role": "system", "content": ROUTER_V2_PROMPT.format(max_tools=self.max_tools)},
            {"role": "user", "content": json.dumps(summary, ensure_ascii=False)},
        ]
        try:
            calls, usage = invoke(messages, specs_for(self.allowlist))
        except Exception as exc:  # 路由失败不应影响主流程
            return self._outcome([], [{"name": None, "reason": type(exc).__name__}],
                                 "fallback", type(exc).__name__, {}, started)

        selections, blocked, seen = [], [], set()
        for call in calls or []:
            name, arguments, error = _unpack(call)
            if name not in self.allowlist:
                blocked.append({"name": name, "reason": "tool_not_allowed"})
                continue
            if error:
                blocked.append({"name": name, "reason": error})
                continue
            errors = validate_arguments(name, arguments)
            if errors:
                blocked.append({"name": name, "reason": "; ".join(errors)})
                continue
            if name in seen:
                blocked.append({"name": name, "reason": "duplicate"})
                continue
            seen.add(name)
            selections.append({"name": name, "arguments": arguments})

        selections.sort(key=lambda item: self.allowlist.index(item["name"]))
        if len(selections) > self.max_tools:
            blocked.extend({"name": item["name"], "reason": "over_budget"}
                           for item in selections[self.max_tools:])
            selections = selections[: self.max_tools]
        policy = "model" if selections else ("blocked" if blocked else "none")
        return self._outcome(selections, blocked, policy, None, usage, started)

    # 方法说明：_outcome 统一路由结果的字段，便于审计与评测复用。
    @staticmethod
    def _outcome(selections, blocked, policy, reason, usage, started):
        return {
            "tools": selections,
            "names": [item["name"] for item in selections],
            "blocked": blocked,
            "policy": policy,
            "reason": reason,
            "usage": usage or {},
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        }
