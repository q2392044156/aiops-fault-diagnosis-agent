"""脚本说明：统一 4 类故障指标、案例四口径、cluster bootstrap 与混淆矩阵。"""

from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
from collections import Counter
from pathlib import Path

# 变量说明：BATCH 映射批次到 gates、数据库和案例目录。
BATCH = {
    "docker": ("resources/evaluation/unified4/docker_gates.json",
               "runtime/unified4/docker_run.sqlite3", "runtime/unified4/docker_cases"),
    "wsl": ("resources/evaluation/unified4/wsl_gates.json",
            "runtime/unified4/wsl_run2.sqlite3", "runtime/unified4/wsl_cases"),
    "recaptured": ("resources/evaluation/unified4/wsl_gates.json",
                   "runtime/unified4/wsl_run2.sqlite3", "runtime/unified4/wsl_cases"),
    "network": ("resources/evaluation/unified4/docker_gates.json",
                "runtime/unified4/docker_run.sqlite3", "runtime/unified4/docker_cases"),
}

# 变量说明：BOOTSTRAP_REPS 是 bootstrap 默认重复次数。
BOOTSTRAP_REPS = 2000
# 变量说明：BOOTSTRAP_SEED 是固定随机种子，保证区间可复现。
BOOTSTRAP_SEED = 20261116


# 方法说明：_wilson 计算独立样本比例的 Wilson 置信区间，保留作参考。
def _wilson(hits, total):
    if not total:
        return None
    z = 1.96
    p = hits / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return [round(max(0, centre - margin), 4), round(min(1, centre + margin), 4)]


# 方法说明：_quantile 计算经验分布的分位数，用于 bootstrap 区间。
def _quantile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = int(math.floor(position))
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


# 方法说明：_interval 取 2.5% 和 97.5% 分位数，得到 95% 区间。
def _interval(values):
    if not values:
        return None
    return [round(_quantile(values, 0.025), 4), round(_quantile(values, 0.975), 4)]


# 方法说明：_bootstrap 按故障族分层、以案例为重采样单元，估计指标不确定性。
def _bootstrap(records, reps, seed):
    if not records or reps <= 0:
        return {}
    by_family = {}
    for record in records:
        by_family.setdefault(record["family"], []).append(record)
    families = sorted(by_family)
    rng = random.Random(seed)
    keys = ("case_top1", "case_first", "case_all_events", "case_any_event",
            "event_top1", "macro_event")
    samples = {key: [] for key in keys}
    for _ in range(reps):
        sampled = []
        for family in families:
            pool = by_family[family]
            sampled.extend(rng.choices(pool, k=len(pool)))
        total = len(sampled)
        if not total:
            continue
        samples["case_top1"].append(
            sum(record["case_majority"] for record in sampled) / total)
        samples["case_first"].append(
            sum(record["case_first"] for record in sampled) / total)
        samples["case_all_events"].append(
            sum(record["case_all_events"] for record in sampled) / total)
        samples["case_any_event"].append(
            sum(record["case_any_event"] for record in sampled) / total)
        events = sum(record["events"] for record in sampled)
        if events:
            samples["event_top1"].append(
                sum(record["event_hits"] for record in sampled) / events)
        family_rates = []
        for family in families:
            family_records = [record for record in sampled if record["family"] == family]
            family_events = sum(record["events"] for record in family_records)
            if family_events:
                family_rates.append(
                    sum(record["event_hits"] for record in family_records) / family_events)
        if family_rates:
            samples["macro_event"].append(sum(family_rates) / len(family_rates))
    return {key: _interval(values) for key, values in samples.items()}


# 方法说明：_load_batches 加载各批次 gates 和报告数据库。
def _load_batches(root):
    cache = {}
    for name, (gates, db, cases) in BATCH.items():
        gate_rows = json.loads((Path(root) / gates).read_text(encoding="utf-8"))
        conn = sqlite3.connect(Path(root) / db)
        cache[name] = (gate_rows, conn, Path(root) / cases)
    return cache


# 方法说明：_evaluate 计算案例/事件指标、cluster bootstrap 区间与混淆矩阵。
def _evaluate(rows, cache, merge_storage=False,
              bootstrap_reps=BOOTSTRAP_REPS, bootstrap_seed=BOOTSTRAP_SEED):
    # 方法说明：norm 在合并模式下把卷/磁盘统一为存储故障。
    def norm(code):
        if merge_storage and code in ("DN_VOLUME", "DISK_IO"):
            return "STORAGE_FAILURE"
        return code

    per_family = {}
    confusion = {}
    details = []
    records = []
    error_events = []
    report_modes = Counter()
    missing_reports = 0
    for row in rows:
        family = "storage" if merge_storage and row["family"] in ("volume", "disk_io") else row["family"]
        gate_rows, conn, _ = cache[row["batch"]]
        gate = next((item for item in gate_rows if item["incident_id"] == row["case_id"]), None)
        status = per_family.setdefault(family, {
            "cases": 0, "case_hits": 0, "case_first_hits": 0,
            "case_all_hits": 0, "case_any_hits": 0,
            "events": 0, "event_hits": 0, "report_modes": Counter(),
        })
        status["cases"] += 1
        event_ranks = []
        event_preds = []
        if gate:
            for event in gate.get("events", []):
                report_row = conn.execute(
                    "SELECT report_json FROM incident_reports WHERE report_id=?",
                    (event.get("report_id"),)).fetchone()
                if not report_row:
                    missing_reports += 1
                    continue
                report = json.loads(report_row[0])
                report_status = report.get("diagnosis_status") or "UNKNOWN"
                report_modes[report_status] += 1
                status["report_modes"][report_status] += 1
                hypotheses = report.get("hypotheses", [])
                codes = [h.get("root_cause_code") for h in hypotheses]
                event_pred = codes[0] if codes else None
                event_preds.append(event_pred)
                rank = next((i for i, code in enumerate(codes, 1)
                             if code == row["root_cause_code"]), None)
                event_ranks.append(rank)
                if rank != 1:
                    error_events.append({
                        "case_id": row["case_id"],
                        "family": family,
                        "source": row["source"],
                        "true": row["root_cause_code"],
                        "event_id": event.get("event_id"),
                        "report_id": event.get("report_id"),
                        "pred": event_pred,
                        "rank": rank,
                    })
        valid = [pred for pred in event_preds if pred]
        pred = Counter(valid).most_common(1)[0][0] if valid else None
        hit = norm(pred) == norm(row["root_cause_code"])
        event_hits = sum(1 for rank in event_ranks if rank == 1)
        first_hit = bool(event_ranks) and event_ranks[0] == 1
        all_hit = bool(event_ranks) and event_hits == len(event_ranks)
        any_hit = event_hits > 0
        status["case_hits"] += int(hit)
        status["case_first_hits"] += int(first_hit)
        status["case_all_hits"] += int(all_hit)
        status["case_any_hits"] += int(any_hit)
        status["events"] += len(event_ranks)
        status["event_hits"] += event_hits
        confusion.setdefault(norm(row["root_cause_code"]), Counter())[norm(pred)] += 1
        details.append({"case_id": row["case_id"], "family": family, "source": row["source"],
                        "true": row["root_cause_code"], "pred": pred, "hit": hit,
                        "case_first_hit": first_hit, "case_all_hit": all_hit,
                        "case_any_hit": any_hit,
                        "event_count": len(event_ranks), "event_top1": event_hits})
        records.append({"family": family, "case_majority": int(hit),
                        "case_first": int(first_hit), "case_all_events": int(all_hit),
                        "case_any_event": int(any_hit),
                        "events": len(event_ranks), "event_hits": event_hits})
    for status in per_family.values():
        status["case_rate"] = round(status["case_hits"] / status["cases"], 4)
        status["case_first_rate"] = round(status["case_first_hits"] / status["cases"], 4)
        status["case_all_rate"] = round(status["case_all_hits"] / status["cases"], 4)
        status["case_any_rate"] = round(status["case_any_hits"] / status["cases"], 4)
        status["event_rate"] = (round(status["event_hits"] / status["events"], 4)
                                if status["events"] else None)
        status["report_modes"] = dict(status["report_modes"])
    families = sorted(per_family)
    macro_case = sum(per_family[name]["case_rate"] for name in families) / len(families)
    event_rates = [per_family[name]["event_rate"] for name in families
                   if per_family[name]["event_rate"] is not None]
    macro_event = sum(event_rates) / len(event_rates) if event_rates else None
    cases = sum(item["cases"] for item in per_family.values())
    case_hits = sum(item["case_hits"] for item in per_family.values())
    case_first_hits = sum(item["case_first_hits"] for item in per_family.values())
    case_all_hits = sum(item["case_all_hits"] for item in per_family.values())
    case_any_hits = sum(item["case_any_hits"] for item in per_family.values())
    events = sum(item["events"] for item in per_family.values())
    event_hits = sum(item["event_hits"] for item in per_family.values())
    bootstrap = _bootstrap(records, bootstrap_reps, bootstrap_seed)
    return {"cases": cases, "case_top1": case_hits,
            "case_top1_rate": round(case_hits / cases, 4) if cases else None,
            "case_ci95": _wilson(case_hits, cases),
            "case_ci95_wilson": _wilson(case_hits, cases),
            "case_ci95_cluster": bootstrap.get("case_top1"),
            "case_first": case_first_hits,
            "case_first_rate": round(case_first_hits / cases, 4) if cases else None,
            "case_first_ci95": bootstrap.get("case_first"),
            "case_first_ci95_wilson": _wilson(case_first_hits, cases),
            "case_all_events": case_all_hits,
            "case_all_events_rate": round(case_all_hits / cases, 4) if cases else None,
            "case_all_events_ci95": bootstrap.get("case_all_events"),
            "case_all_events_ci95_wilson": _wilson(case_all_hits, cases),
            "case_any_event": case_any_hits,
            "case_any_event_rate": round(case_any_hits / cases, 4) if cases else None,
            "case_any_event_ci95": bootstrap.get("case_any_event"),
            "case_any_event_ci95_wilson": _wilson(case_any_hits, cases),
            "events": events, "event_top1": event_hits,
            "event_top1_rate": round(event_hits / events, 4) if events else None,
            "event_ci95": _wilson(event_hits, events),
            "event_ci95_wilson": _wilson(event_hits, events),
            "event_ci95_cluster": bootstrap.get("event_top1"),
            "macro_case": round(macro_case, 4),
            "macro_event": round(macro_event, 4) if macro_event is not None else None,
            "macro_event_ci95": bootstrap.get("macro_event"),
            "report_modes": dict(report_modes),
            "missing_reports": missing_reports,
            "error_events": error_events,
            "per_family": per_family,
            "confusion": {true: dict(preds) for true, preds in confusion.items()},
            "details": details}


# 方法说明：_summary 只保留打印摘要需要的字段。
def _summary(result):
    return {
        "cases": result["cases"],
        "case_majority": result["case_top1"],
        "case_majority_rate": result["case_top1_rate"],
        "case_first": result["case_first"],
        "case_first_rate": result["case_first_rate"],
        "case_all_events": result["case_all_events"],
        "case_all_events_rate": result["case_all_events_rate"],
        "case_any_event": result["case_any_event"],
        "case_any_event_rate": result["case_any_event_rate"],
        "case_majority_ci95_wilson": result["case_ci95_wilson"],
        "case_majority_ci95_cluster": result["case_ci95_cluster"],
        "case_all_events_ci95_cluster": result["case_all_events_ci95"],
        "events": result["events"],
        "event_top1": result["event_top1"],
        "event_top1_rate": result["event_top1_rate"],
        "event_top1_ci95_wilson": result["event_ci95_wilson"],
        "event_top1_ci95_cluster": result["event_ci95_cluster"],
        "macro_event": result["macro_event"],
        "macro_event_ci95_cluster": result["macro_event_ci95"],
        "report_modes": result["report_modes"],
        "missing_reports": result["missing_reports"],
        "error_event_count": len(result["error_events"]),
    }


# 方法说明：main 输出统一 4 类评测结果。
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--split", required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", required=True)
    parser.add_argument("--merge-storage", action="store_true")
    parser.add_argument("--bootstrap-reps", type=int, default=BOOTSTRAP_REPS)
    parser.add_argument("--bootstrap-seed", type=int, default=BOOTSTRAP_SEED)
    args = parser.parse_args(argv)
    root = Path(args.root)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    split = json.loads(Path(args.split).read_text(encoding="utf-8"))
    rows = {row["case_id"]: row for row in manifest["cases"]}
    cache = _load_batches(root)
    test = _evaluate([rows[case] for case in split["test"]], cache,
                     merge_storage=args.merge_storage,
                     bootstrap_reps=args.bootstrap_reps,
                     bootstrap_seed=args.bootstrap_seed)
    train = _evaluate([rows[case] for case in split["train"]], cache,
                      merge_storage=args.merge_storage,
                      bootstrap_reps=args.bootstrap_reps,
                      bootstrap_seed=args.bootstrap_seed)
    payload = {"dataset": manifest.get("dataset", "unified_4_fault"),
               "split_hash": split["split_hash"],
               "bootstrap": {"replicates": args.bootstrap_reps,
                             "seed": args.bootstrap_seed,
                             "unit": "case", "stratified_by": "family"},
               "metric_notes": {
                   "case_majority": "案例内事件根因多数投票",
                   "case_first": "案例最早事件的根因 Top-1",
                   "case_all_events": "案例内所有事件都 Top-1 正确（最差事件口径）",
                   "case_any_event": "案例内至少一个事件 Top-1 正确",
                   "case_ci95": "Wilson 区间；当案例准确率为 100% 时作为保守参考",
                   "case_ci95_cluster": "按 family 分层、以案例为重采样单元的 95% cluster bootstrap；100% 指标会退化为 [1,1]",
                   "report_modes": "报告 diagnosis_status 计数，用于区分模板与 LLM 路径",
               },
               "test": test, "train": train}
    payload["report_modes"] = dict(Counter(test["report_modes"]) + Counter(train["report_modes"]))
    payload["test"].pop("details", None)
    payload["train"].pop("details", None)
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    print(json.dumps({"test": _summary(test), "train": _summary(train)},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
