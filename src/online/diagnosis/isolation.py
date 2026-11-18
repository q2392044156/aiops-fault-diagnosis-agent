"""定义 Agent 评测用例集契约，并校验 adev 与 atest 两套用例互不重叠。"""

import json
from collections import Counter
from pathlib import Path

COMPOSITIONS = {
    "adev": {"routine": 6, "normal_context": 3, "insufficient_evidence": 3,
             "high_risk": 3, "failure_recovery": 2, "prompt_injection": 2,
             "approval_conflict": 1},
    "atest": {"routine": 12, "normal_context": 6, "insufficient_evidence": 6,
              "high_risk": 6, "failure_recovery": 4, "prompt_injection": 4,
              "approval_conflict": 2},
}


def load_cases(path, suite=None):
    """读入一套评测用例，校验数量、类别构成与 atest 的证据与工具策略。"""
    path = Path(path)
    suite = suite or path.stem
    if suite not in COMPOSITIONS:
        raise ValueError(f"Unsupported Agent evaluation suite: {suite}")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    expected_count = 20 if suite == "adev" else 40
    if len(rows) != expected_count or len({row["case_id"] for row in rows}) != expected_count:
        raise ValueError(f"{suite} must contain exactly {expected_count} unique cases")
    if len({row.get("family_id") for row in rows}) != expected_count:
        raise ValueError(f"{suite} must contain unique family_id values")
    if dict(Counter(row.get("category") for row in rows)) != COMPOSITIONS[suite]:
        raise ValueError(f"{suite} category composition changed")
    if suite == "atest":
        required = {"fixture_id", "allowed_tools", "forbidden_tools",
                    "required_evidence_ids", "allowed_evidence_ids",
                    "parameter_constraints", "evidence_summary"}
        for row in rows:
            if not required.issubset(row):
                raise ValueError(f"Atest case is incomplete: {row['case_id']}")
            if not set(row["required_evidence_ids"]).issubset(row["allowed_evidence_ids"]):
                raise ValueError(f"Atest evidence policy is inconsistent: {row['case_id']}")
            if set(row["allowed_tools"]).intersection(row["forbidden_tools"]):
                raise ValueError(f"Atest tool policy overlaps: {row['case_id']}")
    return rows


def validate_isolation(adev_path, atest_path):
    """确认开发集与测试集在 case、family 与 fixture 三个维度都不重叠。"""
    adev = load_cases(adev_path, "adev")
    atest = load_cases(atest_path, "atest")
    checks = {
        "case_ids": {row["case_id"] for row in adev}.isdisjoint(
            row["case_id"] for row in atest),
        "family_ids": {row["family_id"] for row in adev}.isdisjoint(
            row["family_id"] for row in atest),
        "fixture_ids": {row.get("fixture_id") for row in adev if row.get("fixture_id")}.isdisjoint(
            row["fixture_id"] for row in atest),
    }
    if not all(checks.values()):
        raise ValueError(f"Adev/Atest isolation failed: {checks}")
    return checks
