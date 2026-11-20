"""规则检测器的发布身份：不再有训练产物，身份由规则集合与脱敏规格的哈希确定。"""

from aiops_diag.common import key
from offline.ingestion.redact import content, masking_spec, shape_id

from .events import KEYWORDS, SEVERITY, combine

MODEL_RELEASE = "v0.3_rules"
DEPLOYMENT_RELEASE = "v1.0"
SCHEMA_VERSION = 5
MODEL_ID = "severity_rule"
MODEL_FAMILY = "rule"
ANOMALY_SCORE_SEMANTICS = "rule_score_in_0_1_not_calibrated"

PUBLIC_FIELDS = (
    "schema_version", "deployment_release", "release_id", "model_id", "model_family",
    "threshold", "min_lines", "anomaly_score_semantics", "rule_set_hash", "masking_hash",
)


def rule_spec(cfg):
    """把 cfg["detector"] 固化为可哈希的规则集合描述。"""
    detector = cfg["detector"]
    return {
        "threshold": float(detector["threshold"]),
        "min_lines": int(detector["min_lines"]),
        "severity": dict(sorted(SEVERITY.items())),
        "keywords": list(KEYWORDS),
    }


class RuleDetector:
    """在线检测器：级别与关键词打分，不加载任何模型文件。"""

    def __init__(self, cfg):
        self.spec = rule_spec(cfg)
        self.threshold = self.spec["threshold"]
        self.min_lines = self.spec["min_lines"]
        self.manifest = {
            "schema_version": SCHEMA_VERSION,
            "deployment_release": DEPLOYMENT_RELEASE,
            "release_id": MODEL_RELEASE,
            "model_id": MODEL_ID,
            "model_family": MODEL_FAMILY,
            "threshold": self.threshold,
            "min_lines": self.min_lines,
            "anomaly_score_semantics": ANOMALY_SCORE_SEMANTICS,
            "rule_set_hash": key(self.spec),
            "masking_hash": key(masking_spec()),
        }
        self.identity = key(self.manifest)

    def public(self):
        return {name: self.manifest[name] for name in PUBLIC_FIELDS}

    def template(self, row):
        """返回该行的脱敏形状编号；同一形状跨批次稳定。"""
        return shape_id(content(row))

    def score(self, session):
        """按会话内的最高级别与关键词命中数打分，返回 (score, prediction)。"""
        score = combine(session["severity"], session["hits"])
        prediction = int(score >= self.threshold and session["line_count"] >= self.min_lines)
        return score, prediction
