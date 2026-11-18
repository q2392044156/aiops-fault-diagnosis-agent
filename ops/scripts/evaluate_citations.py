"""脚本说明：评测报告引用对关键证据的覆盖率。"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, "src")
sys.path.insert(0, "ops/lab/harness")
sys.path.insert(0, "ops/scripts")
from evaluate_evidence import _rows
from evidence import gold_ids


# _line 从 log_id/source_ref 中取行号。
def _line(value):
    try:
        return int(str(value).rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return None


# main 汇总引用覆盖率。
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--gates", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    gates = json.loads(Path(args.gates).read_text(encoding="utf-8"))
    db = sqlite3.connect(args.database)
    cases_with_gold = cited_gold_total = gold_total = cited_total = 0
    per_case = {}
    for gate in gates:
        case = Path(args.cases) / gate["incident_id"]
        if not (case / "incident.json").is_file():
            continue
        incident, _ = _rows(case, "docker_container" if "wsl" not in str(case) else "wsl")
        gold = {_line(item) for item in gold_ids(incident, _)}
        if not gold:
            continue
        cited = set()
        for event in gate.get("events", []):
            row = db.execute("SELECT report_json FROM incident_reports WHERE report_id=?",
                             (event.get("report_id"),)).fetchone()
            if not row:
                continue
            report = json.loads(row[0])
            for evidence in report.get("evidence", []):
                if evidence.get("kind") == "log":
                    line = _line(evidence.get("source_ref"))
                    if line:
                        cited.add(line)
        cases_with_gold += 1
        gold_total += len(gold)
        cited_total += len(cited)
        cited_gold_total += len(gold & cited)
        per_case[gate["incident_id"]] = {
            "gold": len(gold), "cited": len(cited),
            "cited_gold": len(gold & cited),
            "coverage": round(len(gold & cited) / len(gold), 4) if gold else None,
            "precision": round(len(gold & cited) / len(cited), 4) if cited else None,
        }
    result = {"cases": cases_with_gold, "gold_lines": gold_total,
              "cited_lines": cited_total, "cited_gold": cited_gold_total,
              "coverage_micro": round(cited_gold_total / gold_total, 4)
              if gold_total else None,
              "precision_micro": round(cited_gold_total / cited_total, 4)
              if cited_total else None,
              "per_case": per_case}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("cases", "gold_lines", "cited_lines",
                                             "cited_gold", "coverage_micro",
                                             "precision_micro")}, ensure_ascii=False,
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
