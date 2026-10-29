"""模块说明：对失败样例做归因统计（证据缺失/召回缺失/排序错误）。"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

# 变量说明：ROOT 指向仓库根目录。
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aiops_diag.platform.db import Database

# 变量说明：SIGNALS 是各根因码在日志里的关键信号词。
SIGNALS = {
    "DN_VOLUME": ("no space", "out of space", "diskoutofspace", "failed volume",
                  "too many failed volumes"),
    "DN_HEARTBEAT": ("dead datanode", "lost heartbeat", "removedead", "is dead"),
    "NN_SAFE_MODE": ("safe mode",),
}


# 方法说明：_report 按 map.json 读取诊断报告。
def _report(database, mapping):
    if not mapping:
        return None
    row = database.one("SELECT report_json FROM incident_reports WHERE report_id=?",
                       (mapping.get("report_id"),))
    return json.loads(row["report_json"]) if row else None


# 方法说明：_log_text 读取证据日志并转小写。
def _log_text(case_dir):
    files = list((Path(case_dir) / "evidence" / "logs").glob("*.log"))
    return files[0].read_text(encoding="utf-8").lower() if files else ""


# 方法说明：attribute 统计每个失败样例的归因。
def attribute(database, cases_dir):
    rows = []
    for registry in database.all("SELECT incident_id,record_json FROM incident_registry "
                                 "WHERE status='ACTIVE' ORDER BY incident_id"):
        record = json.loads(registry["record_json"])
        inc = record["incident_id"]
        code = record["labels"]["root_cause_code"]
        case_dir = Path(cases_dir) / inc
        map_path = case_dir / "map.json"
        mapping = json.loads(map_path.read_text(encoding="utf-8")) if map_path.is_file() else None
        report = _report(database, mapping)
        hypotheses = (report or {}).get("hypotheses") or []
        codes = [h.get("root_cause_code") for h in hypotheses]
        if code in codes:
            rank = codes.index(code) + 1
            reason = "hit" if rank == 1 else "ranking_error"
        elif not report:
            reason = "no_report"
        else:
            text = _log_text(case_dir)
            reason = "recall_missing" if any(s in text for s in SIGNALS.get(code, ())) \
                else "evidence_missing"
        rows.append({"incident_id": inc, "code": code, "reason": reason,
                     "rank": (codes.index(code) + 1) if code in codes else None})
    return rows


# 方法说明：summarize 按故障族汇总归因。
def summarize(rows):
    summary = defaultdict(lambda: defaultdict(int))
    for row in rows:
        summary[row["code"]][row["reason"]] += 1
        summary[row["code"]]["total"] += 1
    return {code: dict(values) for code, values in sorted(summary.items())}


# 方法说明：markdown 输出归因表。
def markdown(rows):
    summary = summarize(rows)
    lines = ["| 故障族 | 总数 | 命中 | 证据缺失 | 召回缺失 | 排序错误 |",
             "| --- | --- | --- | --- | --- | --- |"]
    for code, item in summary.items():
        lines.append(f"| {code} | {item['total']} | {item.get('hit', 0)} | "
                     f"{item.get('evidence_missing', 0)} | {item.get('recall_missing', 0)} | "
                     f"{item.get('ranking_error', 0)} |")
    total = {key: sum(item.get(key, 0) for item in summary.values())
             for key in ("total", "hit", "evidence_missing", "recall_missing", "ranking_error")}
    lines.append(f"| **合计** | {total['total']} | {total['hit']} | "
                 f"{total['evidence_missing']} | {total['recall_missing']} | "
                 f"{total['ranking_error']} |")
    return "\n".join(lines)


# 方法说明：main 读取数据库并输出归因结果。
def main(argv=None):
    parser = argparse.ArgumentParser(description="Failure attribution for lab incidents")
    parser.add_argument("--database", required=True)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rows = attribute(Database(args.database), args.cases)
    result = {"summary": summarize(rows), "rows": rows}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    table = markdown(rows)
    output.with_suffix(".md").write_text(table + "\n", encoding="utf-8")
    print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
