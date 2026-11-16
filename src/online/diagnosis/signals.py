"""模块说明：定义可解释的根因信号本体，统一日志打分、根因码排序和证据严重度判断。"""

from __future__ import annotations

import re


# 变量说明：LEVEL_WEIGHT 是日志级别对直接证据的放大或折扣系数。
LEVEL_WEIGHT = {"FATAL": 1.2, "ERROR": 1.2, "WARN": 1.0, "INFO": 0.8, "DEBUG": 0.6}
# 变量说明：ROLE_WEIGHT 区分直接原因、上下文补充和旁证，避免旁证压过主信号。
ROLE_WEIGHT = {"direct": 1.0, "context": 0.35, "support": 0.2}
# 变量说明：STRONG_THRESHOLD 是可判定根因码所需的最低信号强度。
STRONG_THRESHOLD = 1.2
# 变量说明：CODE_ORDER 是分数相同时的稳定排序，不改变实际得分。
CODE_ORDER = {"DN_VOLUME": 0, "NETWORK_CONNECTIVITY": 1, "NN_SAFE_MODE": 2,
              "DN_HEARTBEAT": 3, "NN_AVAILABILITY": 4}


# 变量说明：SIGNAL_RULES 按根因码登记正则、基础权重和证据角色。
SIGNAL_RULES = {
    "DN_VOLUME": (
        (r"\bno\s+space\s+left(?:\s+on\s+device)?\b", 2.3, "direct"),
        (r"\benospc\b", 2.3, "direct"),
        (r"\bdisk\s+full\b", 2.0, "direct"),
        (r"\bno\s+space\b", 2.0, "direct"),
        (r"(?:storage\s+)?volume\b[^\n]{0,80}\b(?:failed|full)\b", 1.4, "direct"),
        (r"\b(?:too\s+many\s+)?failed\s+volumes?\b", 2.3, "direct"),
        (r"\bvolumes?\s+failed\b", 2.1, "direct"),
        (r"\bdirectory\s+is\s+not\s+writable\b", 1.8, "direct"),
        (r"\b0\s+bytes\s+(?:available|free)\b", 1.0, "context"),
    ),
    "NETWORK_CONNECTIVITY": (
        (r"\bretrying\s+connect\b", 2.4, "direct"),
        (r"\bconnection\s+timed\s+out\b", 2.1, "direct"),
        (r"\bno\s+route\s+to\s+host\b", 2.2, "direct"),
        (r"\bnetwork\s+is\s+unreachable\b", 2.2, "direct"),
        (r"\bconnection\s+reset\b", 2.0, "direct"),
    ),
    "NN_AVAILABILITY": (
        (r"\bconnection\s+refused\b", 2.4, "direct"),
        (r"\bfailed\s+to\s+connect\b", 1.8, "direct"),
    ),
    "DN_HEARTBEAT": (
        (r"\bmissed\s+(?:its\s+)?liveness\s+deadline\b", 2.3, "direct"),
        (r"\bliveness\s+deadline\b", 2.1, "direct"),
        (r"\blost\s+heartbeat\b", 2.2, "direct"),
        (r"\b(?:lost|dead|stale)\s+datanode\b", 1.9, "direct"),
        (r"\bremove(?:d)?dead(?:datanode)?\b", 1.9, "direct"),
        (r"\bheartbeat\b[^\n]{0,40}\b(?:lost|expired|timeout|timed\s+out|miss\w*)\b",
         2.0, "direct"),
        (r"\bnot\s+receiv(?:ed|ing)\s+heartbeat\b", 1.7, "direct"),
        (r"\bBLOCK\*\s+(?:ask|schedule)\b[^\n]*\breplicat", 0.4, "support"),
    ),
    "NN_SAFE_MODE": (
        (r"\bsafe\s*mode\b", 2.3, "direct"),
        (r"\bsafemode\b", 2.3, "direct"),
        (r"\bstartup\s+guard\b", 2.2, "direct"),
        (r"\breported\s+blocks?\b[^\n]{0,80}\bthreshold\b", 1.0, "context"),
        (r"\bblocks?\b[^\n]{0,80}\b(?:reach|below|under)\b[^\n]{0,40}\bthreshold\b",
         0.8, "context"),
    ),
}


# 方法说明：_compile 预编译正则，避免逐行重复编译。
def _compile():
    compiled = {}
    for code, rules in SIGNAL_RULES.items():
        compiled[code] = tuple(
            (re.compile(pattern, re.IGNORECASE), weight, role)
            for pattern, weight, role in rules
        )
    return compiled


# 变量说明：COMPILED_RULES 是预编译后的规则表。
COMPILED_RULES = _compile()


# 方法说明：_level 把日志级别归一化为受控取值。
def _level(value):
    level = (value or "").upper()
    return level if level in LEVEL_WEIGHT else "INFO"


# 方法说明：_message 兼容 canonical 与平台证据字段读取日志正文。
def _message(row):
    return (row.get("redacted_message") or row.get("excerpt_redacted")
            or row.get("message") or "").strip()


# 方法说明：analyze_row 对单行日志按正则、权重和角色计算各根因码得分。
def analyze_row(row):
    text = _message(row)
    level = _level(row.get("level"))
    if not text:
        return []
    scored = []
    for code, rules in COMPILED_RULES.items():
        direct, context, support, matched = 0.0, 0.0, 0.0, []
        for pattern, weight, role in rules:
            if not pattern.search(text):
                continue
            weighted = weight * LEVEL_WEIGHT[level]
            if role == "direct":
                direct = max(direct, weighted)
            elif role == "context":
                context += weighted
            else:
                support += weighted
            matched.append({"pattern": pattern.pattern, "weight": weight, "role": role})
        score = direct + context * ROLE_WEIGHT["context"] + support * ROLE_WEIGHT["support"]
        if not matched or score <= 0:
            continue
        role = "direct" if direct else ("context" if context else "support")
        scored.append({"code": code, "score": round(score, 4), "role": role,
                       "matched": matched,
                       "log_id": row.get("log_id") or row.get("source_ref")})
    return scored


# 方法说明：analyze_rows 汇总多行日志，同名根因码取最高分行并保留命中日志。
def analyze_rows(rows):
    best = {}
    for row in rows or []:
        for item in analyze_row(row):
            current = best.get(item["code"])
            if current is None or item["score"] > current["score"]:
                best[item["code"]] = {**item, "log_ids": [item["log_id"]]
                                      if item.get("log_id") else [],
                                      "matched": list(item["matched"])}
            elif item["score"] == current["score"] and item.get("log_id"):
                if item["log_id"] not in current["log_ids"]:
                    current["log_ids"].append(item["log_id"])
    codes = sorted(best.values(),
                   key=lambda item: (-item["score"], CODE_ORDER.get(item["code"], 9)))
    return {"codes": codes, "score": round(codes[0]["score"], 4) if codes else 0.0}


# 方法说明：rank_codes 返回达到阈值的根因码，顺序即证据优先级。
def rank_codes(rows, min_score=STRONG_THRESHOLD):
    analysis = analyze_rows(rows if isinstance(rows, list) else [rows])
    return [item["code"] for item in analysis["codes"] if item["score"] >= float(min_score)]


# 方法说明：signal_strength 返回一组日志中的最高信号强度。
def signal_strength(rows):
    return analyze_rows(rows if isinstance(rows, list) else [rows])["score"]


# 方法说明：signal_codes 返回带分数的根因码，供审计和调试使用。
def signal_codes(rows):
    return analyze_rows(rows if isinstance(rows, list) else [rows])["codes"]


# 方法说明：weak_code_hint 在没有强信号时用上下文或弱词给出保守先验。
def weak_code_hint(text):
    analysis = analyze_rows([{"redacted_message": text or "", "level": "INFO"}])
    codes = analysis["codes"]
    if codes and codes[0]["score"] >= 0.4:
        return codes[0]["code"]
    volume = sum((text or "").lower().count(word) for word in
                 ("volume", "disk", "space", "磁盘", "卷"))
    heartbeat = sum((text or "").lower().count(word) for word in
                    ("heartbeat", "lost datanode", "dead datanode", "心跳", "失联"))
    if volume >= 5 and volume >= 2 * max(1, heartbeat):
        return "DN_VOLUME"
    return None
