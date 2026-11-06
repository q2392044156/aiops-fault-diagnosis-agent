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


# 方法说明：_metrics 计算阈值下的 FPR/Recall。
def _metrics(normal, fault, detector):
    fp = sum(1 for rows in normal if detector.decide(rows)["decision"] == "PASS")
    hits = sum(1 for rows in fault if detector.decide(rows)["decision"] == "PASS")
    return {"threshold": detector.threshold,
            "normal": len(normal), "false_positive": fp,
            "fpr": round(fp / len(normal), 4) if normal else None,
            "fault": len(fault), "detected": hits,
            "recall": round(hits / len(fault), 4) if fault else None}


# 方法说明：main 按案例顺序切分并评测。
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True)
    parser.add_argument("--source-type", choices=("docker_container", "wsl"), required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--target-fpr", type=float, default=0.05)
    parser.add_argument("--diagnosis", default=None)
    args = parser.parse_args(argv)
    cases = [case for case in sorted(Path(args.cases).glob("*"))
             if (case / "incident.json").is_file()]
    split = int(len(cases) * 0.7)
    train, test = cases[:split], cases[split:]
    train_normal, _ = _windows(train, args.source_type)
    test_normal, test_fault = _windows(test, args.source_type)
    detector = TemplateNoveltyDetector(args.target_fpr).fit(train_normal)
    result = {"source_type": args.source_type, "train_cases": len(train),
              "test_cases": len(test), "model": "template_novelty",
              "train_normal_windows": len(train_normal),
              "test_normal_windows": len(test_normal),
              "test_fault_windows": len(test_fault),
              "test": _metrics(test_normal, test_fault, detector)}
    if args.diagnosis and Path(args.diagnosis).is_file():
        rows = json.loads(Path(args.diagnosis).read_text(encoding="utf-8"))["rows"]
        top1 = {row["incident_id"]: bool(row.get("top1")) for row in rows}
        hits = 0
        total = 0
        for case in test:
            window = load_windows(case, args.source_type)
            if not window or not window["fault"]:
                continue
            detected = detector.decide(window["fault"])["decision"] == "PASS"
            hits += int(detected and top1.get(window["incident_id"], False))
            total += 1
        result["end_to_end"] = {"cases": total, "hits": hits,
                                "top1": round(hits / total, 4) if total else None}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
