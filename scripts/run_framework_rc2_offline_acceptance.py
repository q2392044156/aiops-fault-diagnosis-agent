"""Run the separate fixture and real-index RC2 development comparisons."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from aiops_diag.comparison.offline_framework import run
from aiops_diag.data.common import digest


ROOT = Path(__file__).resolve().parents[1]


def render(result):
    lines = [
        "# Framework RC2 离线开发验收", "",
        f"- 生成时间：`{result['generated_at']}`",
        "- 结论范围：开发回归与框架等价性，不是独立效果评测。", "",
        "| 层 | 案例 | 等价 | 两后端预期通过 | 安全门禁 |", 
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for name, item in result["layers"].items():
        summary = item["summary"]
        lines.append(
            f"| {name} | {summary['case_count']} | "
            f"{summary['parity_passed_count']}/{summary['case_count']} | "
            f"{summary['legacy_expectation_passed_count']}/"
            f"{summary['framework_expectation_passed_count']} | "
            f"{'通过' if summary['all_hard_gates_zero'] else '失败'} |")
    lines.extend(["", "## 合并门禁", "",
                  f"- 两层流程全部完成：`{result['gates']['all_cases_completed']}`",
                  f"- 两层 legacy/framework 全部等价：`{result['gates']['all_parity_passed']}`",
                  f"- 真实索引 12/12 达到开发预期：`{result['gates']['real_index_expectations_passed']}`",
                  f"- 安全硬门禁全部为零：`{result['gates']['all_hard_gates_zero']}`", ""])
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-config", type=Path,
                        default=ROOT / "configs/service_v11_framework_base_rc2.yaml")
    parser.add_argument("--framework-config", type=Path,
                        default=ROOT / "configs/service_framework_rc2.yaml")
    parser.add_argument("--work-dir", type=Path,
                        default=ROOT / "runtime/framework_rc2_offline")
    parser.add_argument("--output", type=Path, default=ROOT / "deliverables/results/"
                        "framework_offline_acceptance_rc2.json")
    parser.add_argument("--markdown", type=Path, default=ROOT / "deliverables/results/"
                        "framework_offline_acceptance_rc2.md")
    options = parser.parse_args()
    specs = {
        "flow_fixture": ROOT / "evaluation/framework_parity/dev_cases.jsonl",
        "real_index": ROOT / "evaluation/framework_parity/real_index_agent_cases.jsonl",
    }
    layers = {}
    for name, cases in specs.items():
        layers[name] = run(
            cases, options.legacy_config, options.framework_config,
            options.work_dir / name,
            options.output.parent / f"framework_{name}_comparison_rc2.json",
            options.output.parent / f"framework_{name}_comparison_rc2.md")
    real = layers["real_index"]["summary"]
    gates = {
        "all_cases_completed": all(
            layer["summary"]["case_count"] == (12 if name == "real_index" else 12)
            for name, layer in layers.items()),
        "all_parity_passed": all(layer["summary"]["all_parity_passed"]
                                 for layer in layers.values()),
        "real_index_expectations_passed": (
            real["legacy_expectation_passed_count"] == 12
            and real["framework_expectation_passed_count"] == 12),
        "all_hard_gates_zero": all(layer["summary"]["all_hard_gates_zero"]
                                   for layer in layers.values()),
    }
    result = {
        "schema_version": 1,
        "status": "RC2_DEVELOPMENT_OFFLINE_ACCEPTANCE",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "development_only_not_independent_quality_evidence",
        "configs": {
            "legacy": {"path": str(options.legacy_config.resolve()),
                       "sha256": digest(options.legacy_config)},
            "framework": {"path": str(options.framework_config.resolve()),
                          "sha256": digest(options.framework_config)},
        },
        "gates": gates,
        "passed": all(gates.values()),
        "layers": layers,
    }
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    options.markdown.write_text(render(result), encoding="utf-8")
    print(json.dumps({"status": result["status"], "passed": result["passed"],
                      "gates": gates}, ensure_ascii=False, indent=2))
