"""模块说明：读取服务数据库，输出诊断轨迹指标与失败分类。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 变量说明：ROOT 指向仓库根目录，便于脚本在任意工作目录运行。
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aiops_diag.evaluation.trajectory import aggregate, markdown, summarize
from aiops_diag.platform.db import Database


# 方法说明：_rows 从数据库读取每次诊断的运行、工具调用与报告。
def _rows(database, limit=0):
    query = "SELECT * FROM agent_runs ORDER BY created_at, diagnosis_id"
    runs = database.all(query)
    if limit:
        runs = runs[:limit]
    rows = []
    for run in runs:
        calls = database.all(
            "SELECT tool_name,status,args_hash,ordinal FROM agent_tool_calls "
            "WHERE diagnosis_id=? ORDER BY ordinal", (run["diagnosis_id"],))
        report_row = database.one(
            "SELECT report_json FROM incident_reports WHERE diagnosis_id=?",
            (run["diagnosis_id"],))
        report = json.loads(report_row["report_json"]) if report_row else None
        rows.append(summarize(run, calls, report))
    return rows


# 方法说明：main 计算指标并写出 JSON 与 Markdown 报告。
def main(argv=None):
    parser = argparse.ArgumentParser(description="Agent trajectory evaluation")
    parser.add_argument("--database", required=True)
    parser.add_argument("--output", default=str(ROOT / "resources/evaluation/trajectory/result"))
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    database = Database(args.database)
    rows = _rows(database, args.limit)
    summary = aggregate(rows)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".json").write_text(
        json.dumps({"summary": summary, "runs": rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    table = markdown(rows, summary)
    output.with_suffix(".md").write_text(table + "\n", encoding="utf-8")
    print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
