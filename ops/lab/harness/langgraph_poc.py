"""模块说明：用 LangGraph 后端跑 5 例 WSL 实验并输出对比结果。"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "ops" / "lab" / "harness"))

from ingest import ingest


# 方法说明：_pick 选出有 incident.json 的案例。
def _pick(cases_dir, pattern, count):
    return [path for path in sorted(Path(cases_dir).glob(pattern))
            if (path / "incident.json").is_file()][:count]


# 方法说明：_score 读取报告并按根因码计算 Top-1。
def _score(database, expected):
    connection = sqlite3.connect(database)
    rows = []
    for (payload,) in connection.execute("SELECT report_json FROM incident_reports"):
        body = json.loads(payload)
        codes = [item.get("root_cause_code") for item in body.get("hypotheses", [])]
        event_id = body["incident_id"]
        rows.append({"event_id": event_id, "expected": expected.get(event_id),
                     "codes": codes[:5],
                     "top1": bool(codes and codes[0] == expected.get(event_id))})
    checkpoints = connection.execute(
        "SELECT COUNT(*) FROM langgraph_checkpoints").fetchone()[0]
    return rows, checkpoints


# 方法说明：main 复制案例、用 LangGraph 后端接入并打印结果。
def main(argv=None):
    parser = argparse.ArgumentParser(description="LangGraph PoC on WSL lab cases")
    parser.add_argument("--cases-dir", default="ops/lab/wsl_cases")
    parser.add_argument("--database", default="runtime/lab/langgraph_poc.sqlite3")
    parser.add_argument("--work", default="runtime/lab/langgraph_poc_cases")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cases = (_pick(args.cases_dir, "*volume*", 2)
             + _pick(args.cases_dir, "*heartbeat*", 2)
             + _pick(args.cases_dir, "*safe_mode*", 1))
    work = Path(args.work)
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    Path(args.database).unlink(missing_ok=True)

    expected = {}
    for case in cases:
        target = work / case.name
        shutil.copytree(case, target)
        mapping = ingest(str(target), args.database, agent_backend="langgraph")
        incident = json.loads((target / "incident.json").read_text(encoding="utf-8"))
        expected[mapping["event_id"]] = incident["labels"]["root_cause_code"]

    rows, checkpoints = _score(args.database, expected)
    print("| 案例 | 期望 | 候选前三 | Top-1 |")
    print("| --- | --- | --- | --- |")
    for row in rows:
        print(f"| {row['event_id'][:18]} | {row['expected']} | "
              f"{', '.join(str(code) for code in row['codes'][:3])} | {row['top1']} |")
    hits = sum(row["top1"] for row in rows)
    print(f"\nTop-1: {hits}/{len(rows)}；LangGraph checkpoints: {checkpoints}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
