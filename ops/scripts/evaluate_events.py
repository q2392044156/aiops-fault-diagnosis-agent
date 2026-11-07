"""脚本说明：按窗口事件评测根因 Top-1 与事件级覆盖。"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


# 方法说明：_rank 返回期望根因码在报告中的名次。
def _rank(report, expected):
    for index, hypothesis in enumerate(report.get("hypotheses", []), 1):
        if hypothesis.get("root_cause_code") == expected:
            return index
    return None


# 方法说明：main 汇总事件级指标。
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--gates", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    gates = json.loads(Path(args.gates).read_text(encoding="utf-8"))
    db = sqlite3.connect(args.database)
    expected = {}
    for case in Path(args.cases).glob("*"):
        if (case / "incident.json").is_file():
            incident = json.loads((case / "incident.json").read_text(encoding="utf-8"))
            expected[incident["incident_id"]] = incident["labels"]["root_cause_code"]
    events = []
    incidents = {}
    for gate in gates:
        incident_id = gate["incident_id"]
        hits = []
        for event in gate.get("events", []):
            row = db.execute("SELECT report_json FROM incident_reports WHERE report_id=?",
                             (event.get("report_id"),)).fetchone()
            if not row:
                events.append({"incident_id": incident_id, "event_id": event.get("event_id"),
                               "rank": None})
                hits.append(False)
                continue
            report = json.loads(row[0])
            rank = _rank(report, expected.get(incident_id))
            events.append({"incident_id": incident_id, "event_id": event.get("event_id"),
                           "rank": rank})
            hits.append(rank == 1)
        incidents[incident_id] = any(hits)
    event_top1 = sum(1 for event in events if event["rank"] == 1)
    event_top3 = sum(1 for event in events if event["rank"] and event["rank"] <= 3)
    mrr = sum(1 / event["rank"] for event in events
              if event["rank"]) / len(events) if events else 0.0
    result = {"events": len(events), "event_top1": event_top1,
              "event_top1_rate": round(event_top1 / len(events), 4) if events else None,
              "event_top3": event_top3,
              "event_top3_rate": round(event_top3 / len(events), 4) if events else None,
              "event_mrr": round(mrr, 4),
              "incidents": len(incidents),
              "incident_any_top1": sum(1 for hit in incidents.values() if hit),
              "incident_any_top1_rate": round(
                  sum(1 for hit in incidents.values() if hit) / len(incidents), 4)
              if incidents else None}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
