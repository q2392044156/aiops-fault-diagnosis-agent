"""模块说明：基于模板新颖度的来源检测器。"""

from __future__ import annotations

import json
from math import sqrt
from pathlib import Path

from aiops_diag.detection.templates import content


# 方法说明：_text 兼容 canonical message 与平台 redacted_message。
def _text(row):
    if row.get("message") is None and row.get("redacted_message") is not None:
        row = {**row, "message": row["redacted_message"]}
    return content(row)


# 方法说明：wilson 计算二项比例的 Wilson 置信区间。
def wilson(hits, total, z=1.96):
    if not total:
        return None
    p = hits / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4)]


# 类说明：TemplateNoveltyDetector 用正常窗口的模板集合判断新颖度。
class TemplateNoveltyDetector:
    # 方法说明：__init__ 设置目标误报率。
    def __init__(self, target_fpr=0.05, min_threshold=0.05):
        self.target_fpr = float(target_fpr)
        self.min_threshold = float(min_threshold)
        self.templates = set()
        self.threshold = 0.0

    # 方法说明：fit 在正常窗口上学习模板集合并校准阈值。
    def fit(self, normal_windows):
        self.templates = {_text(row) for rows in normal_windows for row in rows}
        scores = [self.score(rows) for rows in normal_windows if rows]
        if scores:
            scores.sort()
            index = min(len(scores) - 1, int(len(scores) * (1.0 - self.target_fpr)))
            self.threshold = float(scores[index])
        self.threshold = max(self.threshold, self.min_threshold)
        return self

    # 方法说明：score 返回窗口内未见模板的比例。
    def score(self, rows):
        if not rows:
            return 0.0
        unseen = sum(1 for row in rows if _text(row) not in self.templates)
        return round(unseen / len(rows), 4)

    # 方法说明：decide 返回是否异常。
    def decide(self, rows):
        score = self.score(rows)
        return {"decision": "PASS" if score > self.threshold else "REJECT",
                "score": score, "threshold": self.threshold,
                "reason": "novel_template_ratio"}

    # 方法说明：save 把冻结模板与阈值写入 JSON。
    def save(self, path):
        payload = {"schema_version": 1, "model": "template_novelty",
                   "target_fpr": self.target_fpr, "threshold": self.threshold,
                   "min_threshold": self.min_threshold,
                   "templates": sorted(self.templates)}
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(payload, ensure_ascii=False) + "\n",
                              encoding="utf-8")
        return Path(path)

    # 方法说明：load 从 JSON 恢复检测器。
    @classmethod
    def load(cls, path):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        detector = cls(payload.get("target_fpr", 0.05),
                       payload.get("min_threshold", 0.05))
        detector.templates = set(payload.get("templates", []))
        detector.threshold = float(payload.get("threshold", 0.0))
        return detector
