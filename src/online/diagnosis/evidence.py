"""结构化证据选择、去重与充分性评估。"""

from __future__ import annotations

import re
from collections import Counter

from online.diagnosis.signals import STRONG_THRESHOLD, analyze_row, analyze_rows

# WEAK_TERMS 是弱信号，用于覆盖卷/磁盘等启动期证据。
WEAK_TERMS = ("volume", "disk", "storage", "exception", "failed", "error",
              "network", "connection", "timeout", "unreachable", "retrying")
# LEVEL_SCORE 是严重度权重。
LEVEL_SCORE = {"FATAL": 4.0, "ERROR": 3.0, "WARN": 1.8, "INFO": 0.4}


# stack_continuation 判断堆栈续行。
def stack_continuation(message):
    text = (message or "").lstrip()
    return text.startswith("at ") or (text.startswith("... ") and "more" in text)


# _signature 生成去重签名。
def _signature(row):
    message = (row.get("redacted_message") or "").lower()
    if stack_continuation(message):
        return "stack"
    return f'{row.get("level") or ""}|{row.get("component") or ""}|' + re.sub(r"\d+", "<n>", message)


# _cost 估算 token。
def _cost(row):
    return max(1, len(row.get("redacted_message") or "") // 4)


# EvidenceSelector 按信号、严重度、稀有度、组件与时间去重排序。
class EvidenceSelector:
    # __init__ 保存预算和关注组件。
    def __init__(self, limit=50, token_budget=2000, focus_component=None):
        self.limit = int(limit)
        self.token_budget = int(token_budget) if token_budget else None
        self.focus_component = focus_component

    # _prepare 计算候选得分，信号强度复用根因本体而不重复计数关键词。
    def _prepare(self, rows):
        templates = Counter(row.get("template_id") for row in rows
                            if row.get("template_id") is not None)
        scored = []
        for index, row in enumerate(rows):
            message = (row.get("redacted_message") or "").lower()
            analysis = analyze_row(row)
            strength = max((item["score"] for item in analysis), default=0.0)
            codes = [item["code"] for item in analysis if item["score"] >= STRONG_THRESHOLD]
            weak = [word for word in WEAK_TERMS if word in message]
            score = 4.0 * min(3.0, strength)
            if not codes:
                score += 4.0 * len(weak)
            score += LEVEL_SCORE.get((row.get("level") or "").upper(), 0.2)
            template = row.get("template_id")
            if template is not None and templates[template] <= 2:
                score += 0.8
            if rows:
                score += 0.5 * (index / max(1, len(rows) - 1))
            if self.focus_component and row.get("component") == self.focus_component:
                score += 0.8
            reason = "signal" if codes else ("weak_signal" if strength > 0 else
                                             ("severity" if row.get("level") in
                                              ("ERROR", "WARN", "FATAL") else "context"))
            scored.append({**row, "selection_score": round(score, 4),
                           "selection_reason": reason, "signal_strength": round(strength, 4),
                           "signal_codes": codes})
        return scored

    # select 返回预算内、去重后的证据行和质量摘要。
    def select(self, rows):
        scored = self._prepare(rows)
        best = {}
        for item in scored:
            signature = _signature(item)
            current = best.get(signature)
            if current is None or item["selection_score"] > current["selection_score"]:
                best[signature] = item
        items = list(best.values())
        signals = [item for item in items
                   if item.get("selection_reason") in ("signal", "weak_signal")]
        severe = [item for item in items
                  if item.get("level") in ("ERROR", "WARN", "FATAL")]
        tail = []
        for row in scored[-self.limit:]:
            item = best.get(_signature(row))
            if item is not None:
                tail.append(item)
        fallback = sorted(items, key=lambda item: (-item["selection_score"],
                                                    item.get("log_id", "")))
        ordered, seen = [], set()
        for item in signals + severe + tail + fallback:
            signature = _signature(item)
            if signature not in seen:
                ordered.append(item)
                seen.add(signature)
        selected, tokens = [], 0
        for item in ordered:
            cost = _cost(item)
            if self.token_budget and selected and tokens + cost > self.token_budget:
                continue
            selected.append(item)
            tokens += cost
            if len(selected) >= self.limit:
                break
        quality = self.quality(rows, selected)
        return selected, quality

    # quality 汇总结构化证据质量，并给出可审计的根因信号分数。
    def quality(self, pool, selected):
        analysis = analyze_rows(selected)
        has_signal = bool(analysis["codes"])
        has_error = any(row.get("level") in ("ERROR", "FATAL") for row in selected)
        components = sorted({row.get("component") for row in selected if row.get("component")})
        return {
            "sufficient": bool(has_signal or has_error),
            "has_signal": has_signal, "has_error": has_error,
            "selected": len(selected), "pool": len(pool),
            "tokens_est": sum(_cost(row) for row in selected),
            "components": components,
            "levels": dict(Counter(row.get("level") for row in selected)),
            "template_diversity": len({row.get("template_id") for row in selected
                                       if row.get("template_id") is not None}),
            "time_range": [selected[0].get("timestamp"), selected[-1].get("timestamp")]
            if selected else [],
            "detected_codes": [item["code"] for item in analysis["codes"]
                               if item["score"] >= STRONG_THRESHOLD],
            "signal_scores": [{"root_cause_code": item["code"], "score": item["score"],
                               "role": item["role"]} for item in analysis["codes"]],
            "missing": [] if has_signal or has_error else ["signal_or_error_evidence"],
        }
