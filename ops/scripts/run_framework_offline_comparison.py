# 模块说明：实现 run framework offline comparison 相关的辅助流程。
"""Run the development-only legacy/framework offline comparison."""

import argparse
import json
from pathlib import Path

from aiops_diag.evaluation.offline_framework import run


# 变量说明：`ROOT` 保存本模块或数据模型使用的稳定值。
ROOT = Path(__file__).resolve().parents[2]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path,
                        default=ROOT / "resources/evaluation/framework_parity/dev_cases.jsonl")
    parser.add_argument("--legacy-config", type=Path,
                        default=ROOT / "resources/configs/service_v11_framework_base.yaml")
    parser.add_argument("--framework-config", type=Path,
                        default=ROOT / "resources/configs/service_framework_candidate.yaml")
    parser.add_argument("--work-dir", type=Path,
                        default=ROOT / "runtime/offline_framework_comparison")
    parser.add_argument("--json-output", type=Path,
                        default=ROOT / "documentation/results/"
                        "framework_offline_comparison_rc1_02.json")
    parser.add_argument("--markdown-output", type=Path,
                        default=ROOT / "documentation/results/"
                        "framework_offline_comparison_rc1_02.md")
    options = parser.parse_args()
    comparison = run(options.cases, options.legacy_config,
                     options.framework_config, options.work_dir,
                     options.json_output, options.markdown_output)
    print(json.dumps({"status": comparison["status"],
                      "summary": comparison["summary"],
                      "hard_gate_counts": comparison["hard_gate_counts"],
                      "json_output": str(options.json_output.resolve()),
                      "markdown_output": str(options.markdown_output.resolve())},
                     ensure_ascii=False, indent=2))
