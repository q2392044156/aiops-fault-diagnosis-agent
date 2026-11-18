"""脚本说明：磁盘 IO 与卷故障的案例级混淆矩阵。"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

# DISK_IO 是磁盘 IO 根因码。
DISK_IO = "DISK_IO"
# VOLUME 是卷故障根因码。
VOLUME = "DN_VOLUME"


# _predict 读取案例所有 event 的首选根因。
def _predict(gate, db):
    codes = []
    for event in gate.get("events", []):
        row = db.execute("SELECT report_json FROM incident_reports WHERE report_id=?",
                         (event.get("report_id"),)).fetchone()
        if not row:
            continue
        hypotheses = json.loads(row[0]).get("hypotheses", [])
        code = hypotheses[0].get("root_cause_code") if hypotheses else None
        if code:
            codes.append(code)
    return Counter(codes).most_common(1)[0][0] if codes else None


# _rows 构造指定真实根因的案例行。
def _rows(gates, db, cases, code):
    rows = []
    for gate in gates:
        case = Path(cases) / gate["incident_id"]
        incident = case / "incident.json"
        if not incident.is_file():
            continue
        label = json.loads(incident.read_text(encoding="utf-8"))["labels"]["root_cause_code"]
        if label != code:
            continue
        rows.append({"case": gate["incident_id"], "true": code,
                     "pred": _predict(gate, db)})
    return rows


# main 输出磁盘 IO 与卷故障矩阵。
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--disk-gates", required=True)
    parser.add_argument("--disk-db", required=True)
    parser.add_argument("--disk-cases", required=True)
    parser.add_argument("--volume-gates", required=True)
    parser.add_argument("--volume-db", required=True)
    parser.add_argument("--volume-cases", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    dg = json.loads(Path(args.disk_gates).read_text(encoding="utf-8"))
    vg = json.loads(Path(args.volume_gates).read_text(encoding="utf-8"))
    rows = _rows(dg, sqlite3.connect(args.disk_db), args.disk_cases, DISK_IO)
    rows += _rows(vg, sqlite3.connect(args.volume_db), args.volume_cases, VOLUME)
    matrix = {true: dict.fromkeys((DISK_IO, VOLUME, None), 0)
              for true in (DISK_IO, VOLUME)}
    for row in rows:
        matrix[row["true"]][row["pred"]] += 1
    payload = {"rows": rows, "matrix": matrix,
               "misclassified": [row for row in rows if row["pred"] != row["true"]]}
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    print(json.dumps({"matrix": matrix, "misclassified": len(payload["misclassified"])},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
