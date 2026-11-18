"""运行红队用例，输出拦截率、误杀率与未通过清单。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# ROOT 指向仓库根目录，便于脚本在任意工作目录运行。
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from evaluation.redteam import evaluate, load_cases, markdown


# main 执行全部用例并写出 JSON 与 Markdown 结果。
def main(argv=None):
    parser = argparse.ArgumentParser(description="Red team evaluation")
    parser.add_argument("--cases", default=str(ROOT / "ops/redteam/cases.jsonl"))
    parser.add_argument("--output", default=str(ROOT / "resources/evaluation/redteam/result"))
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    result = evaluate(load_cases(args.cases))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    table = markdown(result)
    output.with_suffix(".md").write_text(table + "\n", encoding="utf-8")
    print(table)
    return 0 if not result["summary"]["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
