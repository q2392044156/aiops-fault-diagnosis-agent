# 模块说明：计算当前模块的评测指标并输出结构化结果。
"""Add a failure taxonomy to frozen W10 and future Agent evaluation results."""

from collections import Counter
import json
from pathlib import Path

from aiops_diag.common import digest, save


# 变量说明：`ERROR_CATEGORIES` 保存本模块或数据模型使用的稳定值。
ERROR_CATEGORIES = {
    "DeepSeekJsonError": "invalid_json",
    "DeepSeekError": "provider_error",
    "ValidationError": "invalid_schema",
    "EVALUATION_BUDGET_EXHAUSTED": "evaluation_budget",
}


# 方法说明：`classify_run` 完成当前步骤的业务处理；参数为 `run`。
def classify_run(run):
    results = run["results"]
    categories = Counter(ERROR_CATEGORIES.get(row["error"], "unexpected_error")
                         for row in results if row.get("error"))
    returned = [row for row in results if ERROR_CATEGORIES.get(row.get("error")) not in
                {"provider_error", "evaluation_budget"}]
    return {"schema_version": 1,
            "run_id": run["run_id"], "cases": len(results),
            "failure_categories": dict(sorted(categories.items())),
            "schema_returned_count": len(returned),
            "schema_passed_returned_count": sum(bool(row["schema_valid"])
                                                for row in returned),
            "schema_pass_rate_returned": (sum(bool(row["schema_valid"]) for row in returned)
                                          / len(returned) if returned else None),
            "schema_pass_rate_end_to_end": run["schema_pass_rate"],
            "template_fallback_rate": run["template_fallback_rate"]}


# 方法说明：`classify_summary` 完成当前步骤的业务处理；参数为 `source`。
def classify_summary(source):
    source = Path(source)
    archived = json.loads(source.read_text(encoding="utf-8"))
    runs = [classify_run(run) for run in archived["runs"]]
    failures = Counter()
    for run in runs:
        failures.update(run["failure_categories"])
    returned_count = sum(run["schema_returned_count"] for run in runs)
    returned_passes = sum(run["schema_passed_returned_count"] for run in runs)
    return {"schema_version": 1, "source_sha256": digest(source),
            "source_suite": archived["suite"], "run_count": len(runs),
            "total_cases": sum(run["cases"] for run in runs),
            "failure_categories": dict(sorted(failures.items())),
            "schema_returned_count": returned_count,
            "schema_passed_returned_count": returned_passes,
            "schema_pass_rate_returned": (returned_passes / returned_count
                                          if returned_count else None),
            "runs": runs}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    options = parser.parse_args()
    value = classify_summary(options.source)
    save(options.output, value)
    print(json.dumps({key: value[key] for key in (
        "total_cases", "failure_categories", "schema_returned_count",
        "schema_pass_rate_returned")}, ensure_ascii=False))
