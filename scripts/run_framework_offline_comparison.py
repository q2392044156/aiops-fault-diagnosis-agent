"""Run the development-only legacy/framework offline comparison."""

import argparse
import json
from pathlib import Path

from aiops_diag.comparison.offline_framework import run


ROOT = Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path,
                        default=ROOT / "evaluation/framework_parity/dev_cases.jsonl")
    parser.add_argument("--legacy-config", type=Path,
                        default=ROOT / "configs/service_v11_framework_base.yaml")
    parser.add_argument("--framework-config", type=Path,
                        default=ROOT / "configs/service_framework_candidate.yaml")
    parser.add_argument("--work-dir", type=Path,
                        default=ROOT / "runtime/offline_framework_comparison")
    parser.add_argument("--json-output", type=Path,
                        default=ROOT / "deliverables/results/"
                        "framework_offline_comparison_rc1_02.json")
    parser.add_argument("--markdown-output", type=Path,
                        default=ROOT / "deliverables/results/"
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
