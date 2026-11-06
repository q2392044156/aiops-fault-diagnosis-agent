"""脚本说明：训练模板新颖度检测器并评测正常/故障窗口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")
sys.path.insert(0, "ops/lab/harness")
from aiops_diag.detection.source_detector import TemplateNoveltyDetector
from windows import load_windows


# 方法说明：_windows 返回案例集合的正常/故障窗口。
def _windows(cases, source_type):
    normal, fault = [], []
    for case in cases:
        window = load_windows(case, source_type)
        if not window:
            continue
        if window["normal"]:
            normal.append(window["normal"])
        if window["fault"]:
            fault.append(window["fault"])
    return normal, fault


# 方法说明：_score 返回窗口的检测结果。
def _score(rows, detector):
    return detector.decide(rows)["decision"] == "PASS"


# 方法说明：_fold 在训练集拟合并在测试集评测。
def _fold(train, test, source_type, target_fpr, top1):
    train_normal, _ = _windows(train, source_type)
    test_normal, test_fault = _windows(test, source_type)
    detector = TemplateNoveltyDetector(target_fpr).fit(train_normal)
    fp = sum(1 for rows in test_normal if _score(rows, detector))
    hits = sum(1 for rows in test_fault if _score(rows, detector))
    e2e_hits = 0
    e2e_total = 0
    for case in test:
        window = load_windows(case, source_type)
        if not window or not window["fault"]:
            continue
        detected = _score(window["fault"], detector)
        e2e_hits += int(detected and top1.get(window["incident_id"], False))
        e2e_total += 1
    return {"threshold": detector.threshold, "normal": len(test_normal),
            "false_positive": fp, "fault": len(test_fault), "detected": hits,
            "e2e_hits": e2e_hits, "e2e_total": e2e_total}


# 方法说明：_summary 汇总多折结果。
def _summary(folds):
    normal = sum(item["normal"] for item in folds)
    false_positive = sum(item["false_positive"] for item in folds)
    fault = sum(item["fault"] for item in folds)
    detected = sum(item["detected"] for item in folds)
    e2e_hits = sum(item["e2e_hits"] for item in folds)
    e2e_total = sum(item["e2e_total"] for item in folds)
    return {"thresholds": [item["threshold"] for item in folds],
            "normal": normal, "false_positive": false_positive,
            "fpr": round(false_positive / normal, 4) if normal else None,
            "fault": fault, "detected": detected,
            "recall": round(detected / fault, 4) if fault else None,
            "end_to_end": {"cases": e2e_total, "hits": e2e_hits,
                           "top1": round(e2e_hits / e2e_total, 4) if e2e_total else None}}


# 方法说明：main 执行单次切分或交叉验证。
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True)
    parser.add_argument("--source-type", choices=("docker_container", "wsl"), required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--target-fpr", type=float, default=0.05)
    parser.add_argument("--diagnosis", default=None)
    parser.add_argument("--cv", type=int, default=0)
    parser.add_argument("--save", default=None)
    args = parser.parse_args(argv)
    cases = [case for case in sorted(Path(args.cases).glob("*"))
             if (case / "incident.json").is_file()]
    top1 = {}
    if args.diagnosis and Path(args.diagnosis).is_file():
        rows = json.loads(Path(args.diagnosis).read_text(encoding="utf-8"))["rows"]
        top1 = {row["incident_id"]: bool(row.get("top1")) for row in rows}
    if args.cv and args.cv > 1:
        buckets = [[] for _ in range(args.cv)]
        for index, case in enumerate(cases):
            buckets[index % args.cv].append(case)
        results = []
        for index, bucket in enumerate(buckets):
            train = [case for other, group in enumerate(buckets) if other != index
                     for case in group]
            results.append(_fold(train, bucket, args.source_type, args.target_fpr, top1))
        result = {"source_type": args.source_type, "model": "template_novelty",
                  "cv": args.cv, "cases": len(cases), "test": _summary(results),
                  "folds": results}
    else:
        split = int(len(cases) * 0.7)
        train, test = cases[:split], cases[split:]
        result = {"source_type": args.source_type, "model": "template_novelty",
                  "train_cases": len(train), "test_cases": len(test),
                  "test": _summary([_fold(train, test, args.source_type,
                                          args.target_fpr, top1)])}
    if args.save:
        all_normal, _ = _windows(cases, args.source_type)
        TemplateNoveltyDetector(args.target_fpr).fit(all_normal).save(args.save)
        result["saved"] = str(args.save)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
