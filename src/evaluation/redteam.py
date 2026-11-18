"""红队用例评测：调用真实防御逻辑，统计拦截率与误杀率。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from pydantic import ValidationError

from online.diagnosis.agent import INJECTION, UNSAFE_ACTIONS, Agent
from online.diagnosis.schemas import ActionAdvice, GeneratedReportBody
from online.diagnosis.tool_specs import validate_arguments
from online.knowledge.generation.client import DeepSeekError

# CATEGORIES 是红队用例的分类。
CATEGORIES = ("prompt_injection", "citation", "tool_args", "schema",
              "dangerous_action", "budget")


# _StubClient 用于预算测试，正常路径下返回空报告与零用量。
class _StubClient:
    # complete_json 返回空对象与零用量，便于验证预算守卫。
    def complete_json(self, messages):
        return {}, {"input_tokens": 0, "output_tokens": 0, "estimated_cost_cny": 0.0}


# _injection 用引擎同款正则检测提示注入。
def _injection(case):
    return bool(INJECTION.search(case.get("text") or "")), "injection_regex"


# _citation 用引擎的引用白名单校验检测越权引用。
def _citation(case):
    body = SimpleNamespace(
        hypotheses=[SimpleNamespace(support_ids=case.get("cited") or [], counter_ids=[])],
        checks=[],
    )
    errors = Agent.citation_errors(body, case.get("allowed") or [])
    return bool(errors), "citation_allowlist"


# _tool_args 用工具 Schema 校验检测非法参数。
def _tool_args(case):
    errors = validate_arguments(case.get("tool"), case.get("arguments") or {})
    return bool(errors), "; ".join(errors) or "valid_arguments"


# _schema 用 Pydantic 严格模型检测坏结构。
def _schema(case):
    try:
        GeneratedReportBody.model_validate(case.get("body") or {})
        return False, "schema_ok"
    except ValidationError as exc:
        return True, f"schema_error:{exc.error_count()}"


# _action 用引擎的动作归一化检测危险建议。
def _action(case):
    action = ActionAdvice.model_validate(case.get("action") or {})
    normalized = Agent._normalize_actions([action])[0]
    unsafe = action.action_type in UNSAFE_ACTIONS
    blocked = (not normalized.execution_allowed) and (unsafe or normalized.risk == "high")
    return blocked, "execution_blocked" if blocked else "read_only"


# _budget 在真实引擎的预算守卫上验证超限会被拒绝。
def _budget(case):
    engine = Agent.__new__(Agent)
    engine.client = _StubClient()
    budget = dict(case.get("budget") or {})
    try:
        engine._llm(budget, [])
        return False, "within_budget"
    except DeepSeekError:
        return True, "budget_guard"


# HANDLERS 把分类映射到对应的真实防御函数。
HANDLERS = {
    "prompt_injection": _injection,
    "citation": _citation,
    "tool_args": _tool_args,
    "schema": _schema,
    "dangerous_action": _action,
    "budget": _budget,
}


# load_cases 读取 JSONL 形式的红队用例。
def load_cases(path):
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


# evaluate 逐例执行防御并汇总拦截率与误杀率。
def evaluate(cases):
    rows = []
    for case in cases:
        handler = HANDLERS[case["category"]]
        try:
            blocked, reason = handler(case)
            error = None
        except Exception as exc:
            blocked, reason, error = False, "handler_error", type(exc).__name__
        expected = "block" if case.get("expect", "block") == "block" else "allow"
        rows.append({"case_id": case["case_id"], "category": case["category"],
                     "expect": expected, "blocked": blocked,
                     "ok": blocked == (expected == "block"),
                     "reason": reason, "error": error})
    attacks = [row for row in rows if row["expect"] == "block"]
    benign = [row for row in rows if row["expect"] == "allow"]
    per_category = {}
    for row in attacks:
        item = per_category.setdefault(row["category"], {"total": 0, "blocked": 0})
        item["total"] += 1
        item["blocked"] += int(row["blocked"])
    return {
        "rows": rows,
        "summary": {
            "cases": len(rows),
            "attacks": len(attacks),
            "attack_blocked": sum(row["blocked"] for row in attacks),
            "detection_rate": round(sum(row["blocked"] for row in attacks)
                                    / max(1, len(attacks)), 4),
            "benign": len(benign),
            "false_positives": sum(row["blocked"] for row in benign),
            "false_positive_rate": round(sum(row["blocked"] for row in benign)
                                         / max(1, len(benign)), 4),
            "per_category": per_category,
            "failures": [row["case_id"] for row in rows if not row["ok"]],
        },
    }


# markdown 输出红队结果表。
def markdown(result):
    summary = result["summary"]
    lines = ["| 分类 | 用例 | 拦截 | 拦截率 |", "| --- | --- | --- | --- |"]
    for name, item in sorted(summary["per_category"].items()):
        rate = item["blocked"] / max(1, item["total"])
        lines.append(f"| {name} | {item['total']} | {item['blocked']} | {rate:.0%} |")
    lines.append("")
    lines.append(f"- 攻击用例：{summary['attacks']}，拦截率 {summary['detection_rate']:.2%}")
    lines.append(f"- 正常用例：{summary['benign']}，误杀 {summary['false_positives']} "
                 f"({summary['false_positive_rate']:.2%})")
    lines.append(f"- 未通过用例：{summary['failures'] or '无'}")
    return "\n".join(lines)
