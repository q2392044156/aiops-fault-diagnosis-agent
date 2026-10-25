"""模块说明：执行评测或验收并输出机器可读结果。"""

import argparse
import json
from pathlib import Path

from aiops_diag.diagnosis.framework.evaluation import (evaluate_public_data,
                                                  evaluate_runtime,
                                                  markdown_report)
from aiops_diag.platform.db import Database


# 方法说明：`main` 完成当前步骤的业务处理；参数为 无显式业务参数。
def main():
    parser = argparse.ArgumentParser(description="Evaluate v1.2 public data and runtime safety")
    parser.add_argument("--source-root", type=Path, default=Path("data/external/loghub"))
    parser.add_argument("--database", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    public = evaluate_public_data(
        args.source_root / "processed/diagnostic_snapshots.jsonl",
        args.source_root / "processed/evaluation_labels.jsonl")
    runtime = None
    if args.database:
        db = Database(args.database)
        db.init()
        runtime = evaluate_runtime(db)
    result = {"schema_version": 1, "public_data": public, "runtime": runtime}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.output / "report.md").write_text(markdown_report(public, runtime), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
