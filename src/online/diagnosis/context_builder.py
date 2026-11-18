"""按 token 预算组装报告上下文，支持全量、压缩与最小三种策略。"""

from __future__ import annotations

import re

# STRATEGIES 是受支持的上下文策略。
STRATEGIES = ("full", "compressed", "minimal")
# CJK 用于估算中文 token。
CJK = re.compile(r"[\u4e00-\u9fff]")
# SPACES 用于压缩连续空白。
SPACES = re.compile(r"\s+")
# TRUNCATE 是各策略下单条证据的最大字符数。
TRUNCATE = {"full": 600, "compressed": 320, "minimal": 600}


# estimate_tokens 用“中文按字、英文按 4 字符”的保守规则估算 token。
def estimate_tokens(text):
    value = text or ""
    cjk = len(CJK.findall(value))
    other = len(value) - cjk
    return max(1, int(cjk + other / 4))


# _clean 压缩空白，避免格式噪声占用预算。
def _clean(text):
    return SPACES.sub(" ", text or "").strip()


# _truncate 保留首尾并按比例截断，尽量不丢关键信息。
def _truncate(text, max_chars):
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    head = max(1, int(max_chars * 0.6))
    tail = max(1, max_chars - head - 1)
    return text[:head] + "…" + text[-tail:]


# _dedupe 去掉前缀高度相似的证据，避免同一段文字重复占位。
def _dedupe(items):
    seen, kept = set(), []
    for item in items:
        fingerprint = _clean(item.get("excerpt_redacted"))[:80]
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        kept.append(item)
    return kept


# _select 按策略挑选候选证据，压缩策略保证每类证据至少有一条种子。
def _select(evidence, strategy, max_evidence):
    if strategy == "minimal":
        return list(evidence[:1]), set()
    if strategy == "full":
        return list(evidence[:max_evidence]), set()
    deduped = _dedupe(evidence)
    groups = {}
    for item in deduped:
        groups.setdefault(item.get("kind") or "unknown", []).append(item)
    seed = [items[0] for items in groups.values()]
    rest = [item for item in deduped if all(item is not kept for kept in seed)]
    selected = (seed + rest)[:max_evidence]
    return selected, {row.get("evidence_id") for row in seed}


# _fit 按预算保留证据，种子证据总是保留，其余超出预算则丢弃。
def _fit(selected, seed_ids, strategy, budget_tokens):
    sent, dropped, used = [], [], 0
    for item in selected:
        text = _truncate(_clean(item.get("excerpt_redacted")), TRUNCATE[strategy])
        cost = estimate_tokens(text)
        keep = (strategy == "full" or item.get("evidence_id") in seed_ids
                or used + cost <= budget_tokens)
        if not keep:
            dropped.append(item.get("evidence_id"))
            continue
        sent.append({"evidence_id": item.get("evidence_id"), "kind": item.get("kind"),
                     "excerpt_redacted": text})
        used += cost
    return sent, dropped, used


# _package 组装与报告链一致的输入，并把候选原因的引用裁剪到已发送证据。
def _package(event, hypotheses, rows):
    allowed = {row["evidence_id"] for row in rows}
    candidates = []
    for item in hypotheses:
        candidates.append({
            "hypothesis_id": item.get("hypothesis_id"),
            "description": item.get("description"),
            "component": item.get("component"),
            "support_ids": [name for name in (item.get("support_ids") or []) if name in allowed],
            "counter_ids": [name for name in (item.get("counter_ids") or []) if name in allowed],
            "missing_checks": item.get("missing_checks") or [],
            "support_score": item.get("support_score"),
            "confidence_level": item.get("confidence_level"),
        })
    return {
        "incident": {name: event.get(name) for name in (
            "event_id", "start_time", "end_time", "max_anomaly_score", "threshold")},
        "candidate_hypotheses": candidates,
        "allowed_evidence_ids": sorted(allowed),
        "evidence": rows,
    }


# build_context 按预算裁剪证据，返回可直接喂给报告链的包与统计信息。
def build_context(event, hypotheses, evidence, budget_tokens=1200,
                  strategy="compressed", max_evidence=20):
    strategy = strategy if strategy in STRATEGIES else "compressed"
    selected, seed_ids = _select(evidence or [], strategy, max_evidence)
    rows, dropped, used = _fit(selected, seed_ids, strategy, budget_tokens)
    package = _package(event, hypotheses or [], rows)
    total_chars = sum(len(_clean(item.get("excerpt_redacted"))) for item in evidence or [])
    sent_chars = sum(len(row["excerpt_redacted"]) for row in rows)
    return {
        "package": package,
        "meta": {
            "strategy": strategy,
            "budget_tokens": int(budget_tokens),
            "estimated_tokens": used,
            "evidence_sent": len(rows),
            "evidence_dropped": len(dropped),
            "dropped_ids": dropped,
            "compression_ratio": round(sent_chars / total_chars, 4) if total_chars else 0.0,
            "budget_exceeded": used > int(budget_tokens) and strategy != "full",
        },
    }
