"""脚本说明：评测证据选择的召回、精度与预算消融。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")
sys.path.insert(0, "ops/lab/harness")
from aiops_diag.data.adapters import parse_lines
from aiops_diag.diagnosis.engine import evidence_sufficiency, select_log_rows
from evidence import gold_ids


# 方法说明：_rows 解析案例日志为平台证据行。
def _rows(case, source_type):
    incident = json.loads((case / "incident.json").read_text(encoding="utf-8"))
    log = next((case / "evidence/logs").glob("*.log"))
    parsed = parse_lines(source_type,
                         log.read_text(encoding="utf-8", errors="replace").splitlines(),
                         case.name, incident["timestamps"]["fault_start"])
    rows = [{"log_id": row["log_id"], "level": row["level"],
             "redacted_message": row.get("message") or "",
             "timestamp": row.get("timestamp_utc")} for row in parsed]
    return incident, rows


# 方法说明：main 对多个预算做证据选择消融。
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True)
    parser.add_argument("--source-type", choices=("docker_container", "wsl"), required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--budgets", default="10,30,50,all")
    parser.add_argument("--token-budget", type=int, default=2000)
    args = parser.parse_args(argv)
    budgets = []
    for item in args.budgets.split(","):
        budgets.append(None if item == "all" else int(item))
    results = {}
    label_map = {}
    for budget in budgets:
        key = "all" if budget is None else str(budget)
        total_gold = selected_gold = selected_total = cases_with_gold = 0
        case_full = case_any = tokens = sufficient = 0
        cases_all = 0
        for case in sorted(Path(args.cases).glob("*")):
            if not (case / "incident.json").is_file():
                continue
            incident, rows = _rows(case, args.source_type)
            cases_all += 1
            selected = select_log_rows(
                rows, len(rows) if budget is None else budget,
                None if budget is None else args.token_budget)
            sufficient += int(evidence_sufficiency(selected)["sufficient"])
            gold = gold_ids(incident, rows)
            if not gold:
                continue
            label_map[incident["incident_id"]] = gold
            selected_ids = {row["log_id"] for row in selected}
            gold_set = set(gold)
            total_gold += len(gold_set)
            selected_gold += len(gold_set & selected_ids)
            selected_total += len(selected_ids)
            cases_with_gold += 1
            case_full += int(gold_set <= selected_ids)
            case_any += int(bool(gold_set & selected_ids))
            tokens += sum(len(row.get("redacted_message") or "") for row in selected) // 4
        results[key] = {
            "budget": key, "cases": cases_with_gold, "cases_all": cases_all,
            "gold_lines": total_gold, "selected_lines": selected_total,
            "selected_gold": selected_gold,
            "evidence_recall_micro": round(selected_gold / total_gold, 4) if total_gold else None,
            "evidence_precision_micro": round(selected_gold / selected_total, 4)
            if selected_total else None,
            "case_full_coverage": round(case_full / cases_with_gold, 4)
            if cases_with_gold else None,
            "case_any_coverage": round(case_any / cases_with_gold, 4)
            if cases_with_gold else None,
            "evidence_sufficient_cases": sufficient,
            "evidence_sufficient_rate": round(sufficient / cases_all, 4)
            if cases_all else None,
            "mean_tokens_est": round(tokens / cases_with_gold, 1) if cases_with_gold else None,
        }
    payload = {"budgets": results, "labels": label_map}
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
