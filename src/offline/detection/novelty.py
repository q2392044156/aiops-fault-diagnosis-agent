"""用来源模板的新颖度给会话打分，做 severity-first 的异常判定。"""

from __future__ import annotations

import json
from math import sqrt
from pathlib import Path

from offline.detection.features import content


# _text 兼容 canonical message 与平台 redacted_message。
def _text(row):
    if row.get("message") is None and row.get("redacted_message") is not None:
        row = {**row, "message": row["redacted_message"]}
    return content(row)


# wilson 计算二项比例的 Wilson 置信区间。
def wilson(hits, total, z=1.96):
    if not total:
        return None
    p = hits / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4)]


# TemplateNoveltyDetector 以严重度优先、模板新颖度兜底做门禁。
class TemplateNoveltyDetector:
    # __init__ 设置目标误报率与良性错误白名单。
    def __init__(self, target_fpr=0.05, min_threshold=0.10, benign_errors=None):
        self.target_fpr = float(target_fpr)
        self.min_threshold = float(min_threshold)
        self.benign_errors = set(benign_errors or ())
        self.templates = set()
        self.threshold = 0.0
        self.warn_max = 0

    # fit 在正常窗口上学习模板、WARN 基线与阈值。
    def fit(self, normal_windows):
        self.templates = {_text(row) for rows in normal_windows for row in rows}
        self.warn_max = max((sum(1 for row in rows
                                 if (row.get("level") or "").upper() == "WARN")
                             for rows in normal_windows), default=0)
        scores = [self.score(rows) for rows in normal_windows if rows]
        if scores:
            scores.sort()
            index = min(len(scores) - 1, int(len(scores) * (1.0 - self.target_fpr)))
            self.threshold = float(scores[index])
        self.threshold = max(self.threshold, self.min_threshold)
        return self

    # score 返回窗口内未见模板的比例。
    def score(self, rows):
        if not rows:
            return 0.0
        unseen = sum(1 for row in rows if _text(row) not in self.templates)
        return round(unseen / len(rows), 4)

    # decide 先看 ERROR/FATAL，再用 WARN 与新颖度兜底。
    def decide(self, rows):
        errors = [row for row in rows
                  if (row.get("level") or "").upper() in ("ERROR", "FATAL")
                  and _text(row) not in self.benign_errors]
        if errors:
            return {"decision": "PASS", "score": 1.0, "threshold": self.threshold,
                    "reason": "error_present"}
        warns = [row for row in rows
                 if (row.get("level") or "").upper() == "WARN"]
        if warns:
            novel = [row for row in warns if _text(row) not in self.templates]
            if novel:
                score = round(len(novel) / max(1, len(rows)), 4)
                return {"decision": "PASS", "score": score, "threshold": self.threshold,
                        "reason": "novel_warn"}
            if len(warns) > self.warn_max:
                score = round(len(warns) / max(1, len(rows)), 4)
                return {"decision": "PASS", "score": score, "threshold": self.threshold,
                        "reason": "warn_frequency"}
            return {"decision": "REJECT", "score": self.score(rows),
                    "threshold": self.threshold, "reason": "known_warn"}
        score = self.score(rows)
        return {"decision": "PASS" if score > self.threshold else "REJECT",
                "score": score, "threshold": self.threshold,
                "reason": "novel_info" if score > self.threshold else "no_severe_signal"}

    # save 把冻结模板与阈值写入 JSON。
    def save(self, path):
        payload = {"schema_version": 2, "model": "severity_first_novelty",
                   "target_fpr": self.target_fpr, "threshold": self.threshold,
                   "min_threshold": self.min_threshold, "warn_max": self.warn_max,
                   "benign_errors": sorted(self.benign_errors),
                   "templates": sorted(self.templates)}
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(payload, ensure_ascii=False) + "\n",
                              encoding="utf-8")
        return Path(path)

    # load 从 JSON 恢复检测器。
    @classmethod
    def load(cls, path):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        detector = cls(payload.get("target_fpr", 0.05),
                       payload.get("min_threshold", 0.10),
                       payload.get("benign_errors", []))
        detector.templates = set(payload.get("templates", []))
        detector.threshold = float(payload.get("threshold", 0.0))
        detector.warn_max = int(payload.get("warn_max", 0))
        return detector
