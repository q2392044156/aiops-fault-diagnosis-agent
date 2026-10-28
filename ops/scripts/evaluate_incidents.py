"""模块说明：用 incident 标签与诊断报告计算根因排序与 MTTD 指标。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

# 变量说明：ROOT 指向仓库根目录。
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from aiops_diag.platform.db import Database

# 变量说明：TAXONOMY 是根因码到组件的固定映射。
TAXONOMY = ROOT / "resources/evaluation/v1.2/real_incident_protocol/root_cause_taxonomy.json"


# 方法说明：_wilson 返回二项比例的 95% Wilson 置信区间。
def _wilson(successes, total):
    if not total:
        return None
    z = 1.96
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


# 变量说明：SPLIT_FILE 是冻结测试集清单，存在时优先于哈希规则。
SPLIT_FILE = ROOT / "resources/evaluation/lab/frozen_split.json"


# 方法说明：_split 优先读取冻结清单，否则按事件 ID 哈希稳定划分 20%。
def _split(incident_id, fraction=0.2):
    if SPLIT_FILE.is_file():
        data = json.loads(SPLIT_FILE.read_text(encoding="utf-8"))
        return "test" if incident_id in data.get("test", []) else "train"
    bucket = int(hashlib.sha256(incident_id.encode("utf-8")).hexdigest(), 16) % 100
    return "test" if bucket < fraction * 100 else "train"


# 方法说明：_taxonomy 读取根因码到组件的映射。
def _taxonomy(path=TAXONOMY):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    return {item["code"]: item.get("component") for item in value.get("categories", [])}


# 方法说明：_report 按映射读取诊断报告，缺失时返回 None。
def _report(database, mapping):
    if not mapping:
        return None
    if mapping.get("report_id"):
        row = database.one("SELECT report_json FROM incident_reports WHERE report_id=?",
                           (mapping["report_id"],))
    elif mapping.get("diagnosis_id"):
        row = database.one("SELECT report_json FROM incident_reports WHERE diagnosis_id=?",
                           (mapping["diagnosis_id"],))
    else:
        row = None
    return json.loads(row["report_json"]) if row else None


# 方法说明：_rank 优先按根因码排名；有码但全不匹配时不回退组件。
def _rank(hypotheses, code, component):
    codes = [item.get("root_cause_code") for item in hypotheses]
    if code and any(codes):
        for index, item in enumerate(hypotheses, 1):
            if (item.get("root_cause_code") or "").upper() == code.upper():
                return index, "code"
        return None, None
    for index, item in enumerate(hypotheses, 1):
        if (item.get("component") or "").lower() == (component or "").lower():
            return index, "component"
    return None, None


# 方法说明：_mttd 计算 agent_detected 与 fault_start 的秒差，缺时间戳返回 None。
def _mttd(timestamps):
    start = timestamps.get("fault_start")
    detected = timestamps.get("agent_detected")
    if not start or not detected:
        return None
    from datetime import datetime
    seconds = (datetime.fromisoformat(detected) - datetime.fromisoformat(start)).total_seconds()
    return seconds if seconds >= 0 else None


# 方法说明：evaluate 汇总根因 Top-1/Top-3/MRR 与 MTTD。
def evaluate(database, cases_dir, taxonomy=None):
    taxonomy = taxonomy or _taxonomy()
    rows, excluded = [], []
    for registry in database.all("SELECT incident_id,record_json FROM incident_registry "
                                 "WHERE status='ACTIVE' ORDER BY incident_id"):
        record = json.loads(registry["record_json"])
        labels = record["labels"]
        incident_id = record["incident_id"]
        eligible = (labels.get("confidence") in ("confirmed", "high")
                    and labels.get("review_status") in ("reviewed", "adjudicated")
                    and labels.get("reviewer_id"))
        map_path = Path(cases_dir) / incident_id / "map.json"
        mapping = json.loads(map_path.read_text(encoding="utf-8")) if map_path.is_file() else None
        report = _report(database, mapping)
        expected = taxonomy.get(labels.get("root_cause_code"))
        if not eligible:
            excluded.append({"incident_id": incident_id, "reason": "label_not_confirmed"})
            continue
        if report is None:
            excluded.append({"incident_id": incident_id, "reason": "no_diagnosis"})
            rows.append({"incident_id": incident_id, "expected": expected,
                         "rank": None, "top1": False, "top3": False, "mrr": 0.0,
                         "mttd_seconds": _mttd(record["timestamps"]), "diagnosed": False})
            continue
        hypotheses = report.get("hypotheses") or []
        rank, matched = _rank(hypotheses, labels.get("root_cause_code"), expected)
        rows.append({"incident_id": incident_id, "expected": expected, "rank": rank,
                     "matched_by": matched, "split": _split(incident_id),
                     "top1": rank == 1, "top3": rank is not None and rank <= 3,
                     "mrr": (1.0 / rank) if rank else 0.0,
                     "mttd_seconds": _mttd(record["timestamps"]), "diagnosed": True})

    diagnosed = [row for row in rows if row["diagnosed"]]
    mttd = [row["mttd_seconds"] for row in diagnosed if row["mttd_seconds"] is not None]
    summary = {
        "incidents": len(rows) + len([item for item in excluded
                                      if item["reason"] == "label_not_confirmed"]),
        "eligible": len(rows),
        "diagnosed": len(diagnosed),
        "top1": round(sum(row["top1"] for row in diagnosed) / len(diagnosed), 4)
        if diagnosed else "N/A",
        "top3": round(sum(row["top3"] for row in diagnosed) / len(diagnosed), 4)
        if diagnosed else "N/A",
        "mrr": round(sum(row["mrr"] for row in diagnosed) / len(diagnosed), 4)
        if diagnosed else "N/A",
        "mttd_seconds": round(sum(mttd) / len(mttd), 1) if mttd else "N/A",
        "top1_ci95": _wilson(sum(row["top1"] for row in diagnosed), len(diagnosed)),
        "excluded": len(excluded),
        "exclusion_reasons": {},
    }
    test_rows = [row for row in diagnosed if row["split"] == "test"]
    summary["test"] = {
        "n": len(test_rows),
        "top1": round(sum(row["top1"] for row in test_rows) / len(test_rows), 4)
        if test_rows else "N/A",
        "top1_ci95": _wilson(sum(row["top1"] for row in test_rows), len(test_rows)),
    }
    for item in excluded:
        summary["exclusion_reasons"][item["reason"]] = \
            summary["exclusion_reasons"].get(item["reason"], 0) + 1
    return {"summary": summary, "rows": rows, "excluded": excluded}


# 方法说明：markdown 输出指标表与逐例排名。
def markdown(result):
    summary = result["summary"]
    lines = ["| 指标 | 值 |", "| --- | --- |",
             f"| 事件数 | {summary['incidents']} |",
             f"| 可计入根因指标 | {summary['eligible']} |",
             f"| 有诊断报告 | {summary['diagnosed']} |",
             f"| Top-1 | {summary['top1']} |",
             f"| Top-3 | {summary['top3']} |",
             f"| MRR | {summary['mrr']} |",
             f"| Top-1 95% CI | {summary['top1_ci95']} |",
             f"| 冻结测试集 | n={summary['test']['n']} Top-1={summary['test']['top1']} "
             f"CI={summary['test']['top1_ci95']} |",
             f"| MTTD | {summary['mttd_seconds']} |",
             f"| 排除原因 | {summary['exclusion_reasons']} |",
             "", "| 事件 | 期望组件 | 名次 | 匹配依据 | MTTD(s) |",
             "| --- | --- | --- | --- | --- |"]
    for row in result["rows"]:
        lines.append(f"| {row['incident_id']} | {row['expected']} | "
                     f"{row['rank'] if row['rank'] else '-'} | "
                     f"{row.get('matched_by') or '-'} | "
                     f"{row['mttd_seconds'] if row['mttd_seconds'] is not None else 'N/A'} |")
    return "\n".join(lines)


# 方法说明：main 计算指标并写出 JSON 与 Markdown。
def main(argv=None):
    parser = argparse.ArgumentParser(description="Incident root-cause metrics")
    parser.add_argument("--database", required=True)
    parser.add_argument("--cases", default=str(ROOT / "ops" / "lab" / "cases"))
    parser.add_argument("--output", default=str(ROOT / "resources/evaluation/lab/result"))
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    result = evaluate(Database(args.database), args.cases)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    table = markdown(result)
    output.with_suffix(".md").write_text(table + "\n", encoding="utf-8")
    print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
