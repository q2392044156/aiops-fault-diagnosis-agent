"""计算工具路由实验的指标，并生成可读的对比表。"""

from __future__ import annotations

from aiops_diag.constants import ROUTER_TOOLS

# FREE_PROMPT 是“不设约束”的对照组提示，只给工具名、不给可用性规则。
FREE_PROMPT = """你可以从以下工具中选择：query_metrics、search_similar_incidents。
根据事件摘要选择你认为需要的工具，输出严格 JSON：{"next_tools": []}。"""


# score 把逐例预测汇总成准确率、精确/召回与成本指标。
def score(rows):
    total = len(rows)
    exact = sum(1 for row in rows if set(row["predicted"]) == set(row["expected"]))
    predicted = [set(row["predicted"]) for row in rows]
    expected = [set(row["expected"]) for row in rows]
    true_positive = sum(len(p & e) for p, e in zip(predicted, expected, strict=False))
    selected = sum(len(p) for p in predicted)
    wanted = sum(len(e) for e in expected)
    unnecessary = sum(len(p - e) for p, e in zip(predicted, expected, strict=False))
    missed = sum(len(e - p) for p, e in zip(predicted, expected, strict=False))
    invalid = sum(1 for row in rows
                  if any(name not in ROUTER_TOOLS for name in row["predicted"]))
    fallbacks = sum(1 for row in rows if row.get("policy") == "fallback")
    tokens = sum(int(row.get("usage", {}).get("input_tokens", 0))
                 + int(row.get("usage", {}).get("output_tokens", 0)) for row in rows)
    latency = sum(float(row.get("elapsed_ms", 0.0)) for row in rows)
    precision = true_positive / selected if selected else 1.0
    recall = true_positive / wanted if wanted else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "cases": total,
        "exact_match_rate": round(exact / total, 4) if total else 0.0,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "unnecessary_rate": round(unnecessary / selected, 4) if selected else 0.0,
        "missed_rate": round(missed / wanted, 4) if wanted else 0.0,
        "invalid_name_cases": invalid,
        "fallback_cases": fallbacks,
        "avg_tokens": round(tokens / total, 1) if total else 0.0,
        "avg_latency_ms": round(latency / total, 1) if total else 0.0,
        "total_tokens": tokens,
        "per_tool": _per_tool(rows),
    }


# _per_tool 统计每个工具的命中数、误报数与漏报数。
def _per_tool(rows):
    value = {}
    for name in ROUTER_TOOLS:
        hit = false_positive = false_negative = 0
        for row in rows:
            wanted = name in row["expected"]
            got = name in row["predicted"]
            hit += wanted and got
            false_positive += got and not wanted
            false_negative += wanted and not got
        value[name] = {"hit": hit, "false_positive": false_positive,
                       "false_negative": false_negative}
    return value


# markdown 把三种模式的结果渲染为一张对比表。
def markdown(results):
    lines = ["| 模式 | 完全一致 | 精确率 | 召回率 | F1 | 多余调用率 | 漏调率 | 平均 tokens | 平均延迟 |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for name, item in results.items():
        lines.append(
            f"| {name} | {item['exact_match_rate']:.2%} | {item['precision']:.2%} | "
            f"{item['recall']:.2%} | {item['f1']:.2f} | {item['unnecessary_rate']:.2%} | "
            f"{item['missed_rate']:.2%} | {item['avg_tokens']:.0f} | "
            f"{item['avg_latency_ms']:.0f} ms |")
    lines.append("")
    lines.append("| 模式 | 工具 | 命中 | 误报 | 漏报 |")
    lines.append("| --- | --- | --- | --- | --- |")
    for name, item in results.items():
        for tool, row in item["per_tool"].items():
            lines.append(f"| {name} | {tool} | {row['hit']} | "
                         f"{row['false_positive']} | {row['false_negative']} |")
    return "\n".join(lines)
