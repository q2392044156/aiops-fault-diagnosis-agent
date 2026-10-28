"""模块说明：从数据库记录计算单次诊断的轨迹指标与失败分类。"""

from __future__ import annotations

import json


# 变量说明：NODE_ORDER 是诊断节点的固定顺序，用于计算“走到了第几步”。
NODE_ORDER = {
    "RECEIVED": 0, "VALIDATED": 1, "DETECTED": 2, "EVIDENCE_COLLECTED": 3,
    "RETRIEVED": 4, "HYPOTHESES_RANKED": 5, "REPORT_VALIDATED": 6,
}
# 变量说明：COVERAGE_FLOOR 低于该值时标记“证据利用率偏低”。
COVERAGE_FLOOR = 0.5
# 变量说明：BUDGET_PRESSURE 预算使用率超过该值时标记“预算压力”。
BUDGET_PRESSURE = 0.8
# 变量说明：ABSTAIN_STATUS 是“证据不足、拒绝作答”的合法状态。
ABSTAIN_STATUS = "INSUFFICIENT_EVIDENCE"


# 方法说明：_json 容错地解析数据库中的 JSON 字符串字段。
def _json(value, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


# 方法说明：_cited 汇总报告里所有引用到的证据编号。
def _cited(report):
    cited = set()
    for item in report.get("hypotheses") or []:
        cited.update(item.get("support_ids") or [])
        cited.update(item.get("counter_ids") or [])
    for item in report.get("checks") or []:
        cited.update(item.get("citation_ids") or [])
    return cited


# 方法说明：classify 根据运行状态与报告给出 clean/recovered/degraded/failed 判定。
def classify(run, report, failures):
    if run.get("status") == "FAILED" or report is None:
        return "failed"
    if report.get("diagnosis_status") == ABSTAIN_STATUS:
        return "abstained"
    if report.get("diagnosis_status") == "DEGRADED_TEMPLATE":
        return "degraded"
    if failures:
        return "recovered"
    return "clean"


# 方法说明：summarize 计算单次诊断的步骤、工具、证据、预算与问题标记。
def summarize(run, tool_calls, report):
    state = _json(run.get("state_json"), {})
    budget = _json(run.get("budget_json"), {})
    calls = list(tool_calls or [])
    names = [call.get("tool_name") for call in calls]
    failures = [call for call in calls if call.get("status") != "SUCCEEDED"]
    seen, retries = set(), 0
    for call in calls:
        identity = (call.get("tool_name"), call.get("args_hash"))
        if identity in seen:
            retries += 1
        seen.add(identity)

    evidence = (report or {}).get("evidence") or []
    available = {item.get("evidence_id") for item in evidence if item.get("evidence_id")}
    cited = _cited(report or {})
    ungrounded = sorted(cited - available)
    coverage = len(cited & available) / len(available) if available else 0.0
    max_tokens = max(1, int(budget.get("max_tokens", 1)))
    max_active = max(1, int(budget.get("max_active_ms", 1)))
    token_ratio = int(budget.get("tokens", 0)) / max_tokens
    active_ratio = int(budget.get("active_ms", 0)) / max_active

    flags = []
    if failures:
        flags.append("tool_failure")
    if retries:
        flags.append("retry_loop")
    if ungrounded:
        flags.append("ungrounded_citation")
    if evidence and coverage < COVERAGE_FLOOR:
        flags.append("low_evidence_utilization")
    if not evidence and (report or {}).get("diagnosis_status") == "EVIDENCE_SUPPORTED":
        flags.append("no_evidence")
    if max(token_ratio, active_ratio) > BUDGET_PRESSURE:
        flags.append("budget_pressure")
    if (report or {}).get("diagnosis_status") == "DEGRADED_TEMPLATE":
        flags.append("degraded_report")
    if len((report or {}).get("review_reasons") or []) >= 3:
        flags.append("review_overload")

    node = run.get("current_node") or "RECEIVED"
    return {
        "diagnosis_id": run.get("diagnosis_id"),
        "revision": run.get("revision"),
        "mode": run.get("mode"),
        "status": run.get("status"),
        "verdict": classify(run, report, failures),
        "steps": NODE_ORDER.get(node, 0) + 1,
        "tool_calls": len(calls),
        "unique_tools": len(set(name for name in names if name)),
        "failed_calls": len(failures),
        "retries": retries,
        "tool_sequence": names,
        "evidence_available": len(available),
        "evidence_cited": len(cited & available),
        "evidence_coverage": round(coverage, 4),
        "ungrounded_citations": ungrounded,
        "llm_calls": int(budget.get("llm_calls", 0)),
        "tokens": int(budget.get("tokens", 0)),
        "token_ratio": round(token_ratio, 4),
        "active_ratio": round(active_ratio, 4),
        "estimated_cost_cny": round(float(budget.get("estimated_cost_cny", 0.0)), 6),
        "requires_review": bool((report or {}).get("requires_review")),
        "review_reasons": list((report or {}).get("review_reasons") or []),
        "router_policy": (state.get("router") or {}).get("policy"),
        "router_blocked": len((state.get("router") or {}).get("blocked") or []),
        "errors": [item.get("stage") for item in (state.get("errors") or [])],
        "flags": flags,
    }


# 方法说明：aggregate 把多次诊断的轨迹汇总为比率与均值。
def aggregate(rows):
    total = len(rows)
    if not total:
        return {"runs": 0}
    verdicts = {}
    for row in rows:
        verdicts[row["verdict"]] = verdicts.get(row["verdict"], 0) + 1
    flags = {}
    for row in rows:
        for name in row["flags"]:
            flags[name] = flags.get(name, 0) + 1
    return {
        "runs": total,
        "verdicts": verdicts,
        "avg_steps": round(sum(row["steps"] for row in rows) / total, 2),
        "avg_tool_calls": round(sum(row["tool_calls"] for row in rows) / total, 2),
        "avg_llm_calls": round(sum(row["llm_calls"] for row in rows) / total, 2),
        "avg_tokens": round(sum(row["tokens"] for row in rows) / total, 1),
        "avg_evidence_coverage": round(
            sum(row["evidence_coverage"] for row in rows) / total, 4),
        "retry_rate": round(sum(row["retries"] for row in rows)
                            / max(1, sum(row["tool_calls"] for row in rows)), 4),
        "failure_rate": round(sum(1 for row in rows if row["failed_calls"]) / total, 4),
        "ungrounded_runs": sum(1 for row in rows if row["ungrounded_citations"]),
        "flag_counts": flags,
        "total_cost_cny": round(sum(row["estimated_cost_cny"] for row in rows), 6),
    }


# 方法说明：pass_pow_k 计算 k 次重复中全部通过的比例（k=1 即 pass@1）。
def pass_pow_k(outcomes):
    if not outcomes:
        return 0.0
    return round(sum(1 for runs in outcomes if runs and all(runs)) / len(outcomes), 4)


# 方法说明：markdown 输出逐例轨迹表与汇总指标。
def markdown(rows, summary):
    lines = ["| 诊断 | 判定 | 步骤 | 工具调用 | 失败 | 重试 | 证据覆盖 | tokens | 问题 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for row in rows:
        flags = ", ".join(row["flags"]) or "-"
        lines.append(
            f"| {row['diagnosis_id']} | {row['verdict']} | {row['steps']}/7 | "
            f"{row['tool_calls']} | {row['failed_calls']} | {row['retries']} | "
            f"{row['evidence_coverage']:.0%} | {row['tokens']} | {flags} |")
    lines.append("")
    lines.append("## 汇总")
    lines.append("")
    lines.append(f"- 运行数：{summary.get('runs', 0)}")
    lines.append(f"- 判定分布：{summary.get('verdicts', {})}")
    lines.append(f"- 平均步骤：{summary.get('avg_steps', 0)} / 7")
    lines.append(f"- 平均工具调用：{summary.get('avg_tool_calls', 0)}")
    lines.append(f"- 重试率：{summary.get('retry_rate', 0):.2%}")
    lines.append(f"- 工具失败率：{summary.get('failure_rate', 0):.2%}")
    lines.append(f"- 未落地引用：{summary.get('ungrounded_runs', 0)} 次")
    lines.append(f"- 平均证据覆盖：{summary.get('avg_evidence_coverage', 0):.2%}")
    lines.append(f"- 问题标记：{summary.get('flag_counts', {})}")
    lines.append(f"- 总成本：¥{summary.get('total_cost_cny', 0):.4f}")
    return "\n".join(lines)
