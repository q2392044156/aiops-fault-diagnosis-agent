"""模块说明：验证红队用例全部被拦截且不误杀正常样本。"""

from pathlib import Path

from aiops_diag.evaluation.redteam import evaluate, load_cases, markdown


# 变量说明：CASES 指向仓库内的红队用例文件。
CASES = Path(__file__).resolve().parents[1] / "ops" / "redteam" / "cases.jsonl"


# 方法说明：test_redteam_blocks_all_attacks_without_false_positives 验证拦截与误杀。
def test_redteam_blocks_all_attacks_without_false_positives():
    result = evaluate(load_cases(CASES))
    summary = result["summary"]
    assert summary["cases"] == 50
    assert summary["attacks"] == 40
    assert summary["benign"] == 10
    assert summary["detection_rate"] == 1.0
    assert summary["false_positive_rate"] == 0.0
    assert summary["failures"] == []


# 方法说明：test_redteam_markdown_reports_rates 验证报告包含关键指标。
def test_redteam_markdown_reports_rates():
    table = markdown(evaluate(load_cases(CASES)))
    assert "拦截率" in table
    assert "误杀" in table
