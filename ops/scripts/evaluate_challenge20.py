"""脚本说明：按扰动组评估 challenge20 的案例级与事件级诊断指标。"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import Counter
from pathlib import Path

# ROOT 是仓库根目录。
ROOT = Path(__file__).resolve().parents[2]
# DEFAULT_MANIFEST 是挑战集清单。
DEFAULT_MANIFEST = ROOT / "resources" / "evaluation" / "challenge20" / "manifest.json"
# DEFAULT_GATES 是门禁/事件重放结果。
DEFAULT_GATES = ROOT / "resources" / "evaluation" / "challenge20" / "gates.json"
# DEFAULT_DB 是重放生成的报告数据库，位于 ignored runtime。
DEFAULT_DB = ROOT / "runtime" / "challenge20" / "events_committed.sqlite3"
# DEFAULT_OUTPUT 是挑战集指标输出。
DEFAULT_OUTPUT = ROOT / "resources" / "evaluation" / "challenge20" / "results.json"


# _wilson 计算案例或事件比例的 Wilson 95% 区间。
def _wilson(hits: int, total: int) -> list[float] | None:
    if not total:
        return None
    z = 1.96
    p = hits / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return [round(max(0.0, centre - margin), 4), round(min(1.0, centre + margin), 4)]


# _report_codes 从报告 JSON 中按候选顺序取出根因码。
def _report_codes(raw: str | None) -> tuple[list[str], str | None]:
    if not raw:
        return [], None
    report = json.loads(raw)
    codes = [item.get("root_cause_code") for item in report.get("hypotheses") or []
             if item.get("root_cause_code")]
    return codes, report.get("diagnosis_status")


# _rate 返回命中数和比例，零样本时比例为 None。
def _rate(hits: int, total: int) -> dict:
    return {"hits": hits, "total": total, "rate": round(hits / total, 4) if total else None,
            "ci95": _wilson(hits, total)}


# main 读取清单、门禁和报告，输出按组/故障族的指标与错误事件。
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--gates", default=str(DEFAULT_GATES))
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    gates = json.loads(Path(args.gates).read_text(encoding="utf-8"))
    conn = sqlite3.connect(args.db)
    gate_by_case = {row["incident_id"]: row for row in gates}
    details = []
    report_modes = Counter()
    gate_passed = 0
    for case in manifest["cases"]:
        gate = gate_by_case.get(case["case_id"], {})
        if gate.get("gate_decision") == "PASS":
            gate_passed += 1
        expected = case["root_cause_code"]
        events = []
        for event in gate.get("events", []):
            row = conn.execute("select report_json from incident_reports where report_id=?",
                               (event["report_id"],)).fetchone()
            codes, mode = _report_codes(row[0] if row else None)
            if mode:
                report_modes[mode] += 1
            first = codes[0] if codes else None
            events.append({
                "event_id": event["event_id"],
                "report_id": event["report_id"],
                "pred": first,
                "preds": codes,
                "hit": first == expected,
                "rank": codes.index(expected) + 1 if expected in codes else None,
                "gate_reason": event.get("gate_reason"),
                "gate_score": event.get("gate_score"),
            })
        votes = Counter(event["pred"] for event in events if event["pred"])
        majority = votes.most_common(1)[0][0] if votes else None
        details.append({
            **case,
            "gate_decision": gate.get("gate_decision"),
            "gate_reason": gate.get("gate_reason"),
            "pred": majority,
            "hit": majority == expected,
            "first_hit": bool(events and events[0]["hit"]),
            "all_hit": bool(events and all(event["hit"] for event in events)),
            "any_hit": bool(events and any(event["hit"] for event in events)),
            "event_count": len(events),
            "event_hits": sum(event["hit"] for event in events),
            "events": events,
        })

    groups = {}
    for name in ("format_time", "evidence_drop", "paraphrase", "paraphrase_distractor"):
        rows = [detail for detail in details if detail["group"] == name]
        events = sum(detail["event_count"] for detail in rows)
        groups[name] = {
            "cases": len(rows),
            "case_majority": _rate(sum(detail["hit"] for detail in rows), len(rows)),
            "case_first": _rate(sum(detail["first_hit"] for detail in rows), len(rows)),
            "case_all_events": _rate(sum(detail["all_hit"] for detail in rows), len(rows)),
            "case_any_event": _rate(sum(detail["any_hit"] for detail in rows), len(rows)),
            "events": _rate(sum(detail["event_hits"] for detail in rows), events),
        }
    families = {}
    for name in ("volume", "heartbeat", "safe_mode"):
        rows = [detail for detail in details if detail["family"] == name]
        events = sum(detail["event_count"] for detail in rows)
        families[name] = {
            "cases": len(rows),
            "case_majority": _rate(sum(detail["hit"] for detail in rows), len(rows)),
            "case_all_events": _rate(sum(detail["all_hit"] for detail in rows), len(rows)),
            "events": _rate(sum(detail["event_hits"] for detail in rows), events),
        }
    events_total = sum(detail["event_count"] for detail in details)
    payload = {
        "dataset": manifest["dataset"],
        "synthetic": True,
        "not_independent": True,
        "cases": len(details),
        "events": events_total,
        "gate_passed": gate_passed,
        "gate_decision": _rate(gate_passed, len(details)),
        "case_majority": _rate(sum(detail["hit"] for detail in details), len(details)),
        "case_first": _rate(sum(detail["first_hit"] for detail in details), len(details)),
        "case_all_events": _rate(sum(detail["all_hit"] for detail in details), len(details)),
        "case_any_event": _rate(sum(detail["any_hit"] for detail in details), len(details)),
        "event_top1": _rate(sum(detail["event_hits"] for detail in details), events_total),
        "report_modes": dict(report_modes),
        "groups": groups,
        "families": families,
        "errors": [
            {"case_id": detail["case_id"], "family": detail["family"],
             "group": detail["group"], "expected": detail["root_cause_code"],
             "pred": detail["pred"], "events": [
                 {"event_id": event["event_id"], "pred": event["pred"],
                  "preds": event["preds"], "rank": event["rank"]}
                 for event in detail["events"] if not event["hit"]]}
            for detail in details if not detail["hit"]
        ],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(f"gate {gate_passed}/{len(details)}  cases {payload['case_majority']['hits']}/"
          f"{payload['cases']}  events {payload['event_top1']['hits']}/{events_total}")
    for name, row in groups.items():
        print(f"{name:22} cases {row['case_majority']['hits']}/{row['cases']} "
              f"all {row['case_all_events']['hits']}/{row['cases']} "
              f"events {row['events']['hits']}/{row['events']['total']}")
    print("report_modes", dict(report_modes))


if __name__ == "__main__":
    main()
