"""脚本说明：统一 5 类故障指标与混淆矩阵。"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from collections import Counter
from pathlib import Path

# 变量说明：BATCH 映射批次到 gates、数据库和案例目录。
BATCH = {
    "docker": ("resources/evaluation/unified/docker_gates.json",
               "runtime/unified/docker_run.sqlite3", "runtime/unified/docker_cases"),
    "wsl": ("resources/evaluation/unified/wsl_gates.json",
            "runtime/unified/wsl_run.sqlite3", "runtime/unified/wsl_cases"),
    "recaptured": ("resources/evaluation/unified/wsl_gates.json",
                   "runtime/unified/wsl_run.sqlite3", "runtime/unified/wsl_cases"),
    "network": ("resources/evaluation/unified/docker_gates.json",
                "runtime/unified/docker_run.sqlite3", "runtime/unified/docker_cases"),
    "disk_io": ("resources/evaluation/unified/wsl_gates.json",
                "runtime/unified/wsl_run.sqlite3", "runtime/unified/wsl_cases"),
}


# 方法说明：_wilson 计算比例的 Wilson 置信区间。
def _wilson(hits, total):
    if not total:
        return None
    z = 1.96
    p = hits / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return [round(max(0, centre - margin), 4), round(min(1, centre + margin), 4)]


# 方法说明：_load_batches 加载各批次 gates 和报告数据库。
def _load_batches(root):
    cache = {}
    for name, (gates, db, cases) in BATCH.items():
        gate_rows = json.loads((Path(root) / gates).read_text(encoding="utf-8"))
        conn = sqlite3.connect(Path(root) / db)
        cache[name] = (gate_rows, conn, Path(root) / cases)
    return cache


# 方法说明：_evaluate 计算案例/事件指标与混淆矩阵。
def _evaluate(rows, cache, merge_storage=False):
    # 方法说明：norm 在合并模式下把卷/磁盘统一为存储故障。
    def norm(code):
        if merge_storage and code in ("DN_VOLUME", "DISK_IO"):
            return "STORAGE_FAILURE"
        return code

    per_family = {}
    confusion = {}
    details = []
    for row in rows:
        family = "storage" if merge_storage and row["family"] in ("volume", "disk_io") else row["family"]
        gate_rows, conn, _ = cache[row["batch"]]
        gate = next((item for item in gate_rows if item["incident_id"] == row["case_id"]), None)
        event_ranks = []
        preds = []
        if gate:
            for event in gate.get("events", []):
                report_row = conn.execute(
                    "SELECT report_json FROM incident_reports WHERE report_id=?",
                    (event.get("report_id"),)).fetchone()
                if not report_row:
                    continue
                hypotheses = json.loads(report_row[0]).get("hypotheses", [])
                codes = [h.get("root_cause_code") for h in hypotheses]
                preds.append(codes[0] if codes else None)
                rank = next((i for i, code in enumerate(codes, 1)
                             if code == row["root_cause_code"]), None)
                event_ranks.append(rank)
        valid = [p for p in preds if p]
        pred = Counter(valid).most_common(1)[0][0] if valid else None
        hit = norm(pred) == norm(row["root_cause_code"])
        per_family.setdefault(family, {"cases": 0, "case_hits": 0,
                                       "events": 0, "event_hits": 0})
        status = per_family[family]
        status["cases"] += 1
        status["case_hits"] += int(hit)
        status["events"] += len(event_ranks)
        status["event_hits"] += sum(1 for rank in event_ranks if rank == 1)
        confusion.setdefault(norm(row["root_cause_code"]), Counter())[norm(pred)] += 1
        details.append({"case_id": row["case_id"], "family": family, "source": row["source"],
                        "true": row["root_cause_code"], "pred": pred, "hit": hit,
                        "event_count": len(event_ranks),
                        "event_top1": sum(1 for rank in event_ranks if rank == 1)})
    for status in per_family.values():
        status["case_rate"] = round(status["case_hits"] / status["cases"], 4)
        status["event_rate"] = (round(status["event_hits"] / status["events"], 4)
                                if status["events"] else None)
    families = sorted(per_family)
    macro_case = sum(per_family[name]["case_rate"] for name in families) / len(families)
    macro_event = sum(per_family[name]["event_rate"] for name in families) / len(families)
    cases = sum(item["cases"] for item in per_family.values())
    case_hits = sum(item["case_hits"] for item in per_family.values())
    events = sum(item["events"] for item in per_family.values())
    event_hits = sum(item["event_hits"] for item in per_family.values())
    return {"cases": cases, "case_top1": case_hits,
            "case_top1_rate": round(case_hits / cases, 4) if cases else None,
            "case_ci95": _wilson(case_hits, cases),
            "events": events, "event_top1": event_hits,
            "event_top1_rate": round(event_hits / events, 4) if events else None,
            "event_ci95": _wilson(event_hits, events),
            "macro_case": round(macro_case, 4),
            "macro_event": round(macro_event, 4),
            "per_family": per_family,
            "confusion": {true: dict(preds) for true, preds in confusion.items()},
            "details": details}


# 方法说明：main 输出统一 5 类评测结果。
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--split", required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", required=True)
    parser.add_argument("--merge-storage", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    split = json.loads(Path(args.split).read_text(encoding="utf-8"))
    rows = {row["case_id"]: row for row in manifest["cases"]}
    cache = _load_batches(root)
    test = _evaluate([rows[case] for case in split["test"]], cache,
                     merge_storage=args.merge_storage)
    train = _evaluate([rows[case] for case in split["train"]], cache,
                      merge_storage=args.merge_storage)
    payload = {"dataset": "unified_5_fault", "split_hash": split["split_hash"],
               "test": test, "train": train}
    payload["test"].pop("details", None)
    payload["train"].pop("details", None)
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    print(json.dumps({"test": {k: test[k] for k in (
        "cases", "case_top1_rate", "case_ci95", "events", "event_top1_rate",
        "event_ci95", "macro_case", "macro_event")},
        "train": {k: train[k] for k in ("cases", "case_top1_rate", "events",
                                        "event_top1_rate", "macro_case", "macro_event")}},
        ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
