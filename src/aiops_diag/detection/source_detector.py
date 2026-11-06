"""模块说明：基于模板新颖度的来源检测器。"""

from __future__ import annotations

from aiops_diag.detection.templates import content


# 类说明：TemplateNoveltyDetector 用正常窗口的模板集合判断新颖度。
class TemplateNoveltyDetector:
    # 方法说明：__init__ 设置目标误报率。
    def __init__(self, target_fpr=0.05):
        self.target_fpr = float(target_fpr)
        self.templates = set()
        self.threshold = 0.0

    # 方法说明：fit 在正常窗口上学习模板集合并校准阈值。
    def fit(self, normal_windows):
        self.templates = {content(row) for rows in normal_windows for row in rows}
        scores = [self.score(rows) for rows in normal_windows if rows]
        if scores:
            scores.sort()
            index = min(len(scores) - 1, int(len(scores) * (1.0 - self.target_fpr)))
            self.threshold = float(scores[index])
        return self

    # 方法说明：score 返回窗口内未见模板的比例。
    def score(self, rows):
        if not rows:
            return 0.0
        unseen = sum(1 for row in rows if content(row) not in self.templates)
        return round(unseen / len(rows), 4)

    # 方法说明：decide 返回是否异常。
    def decide(self, rows):
        score = self.score(rows)
        return {"decision": "PASS" if score > self.threshold else "REJECT",
                "score": score, "threshold": self.threshold,
                "reason": "novel_template_ratio"}
