"""脚本说明：用统一时间/组件窗口训练并评测门禁。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, "src")
from aiops_diag.data.windows import load_case_windows, load_normal_windows
from aiops_diag.detection.source_detector import TemplateNoveltyDetector, wilson


# 方法说明：_fault_start 返回案例的故障开始时间戳。
def _fault_start(case):
    incident = json.loads((Path(case) / "incident.json").read_text(encoding="utf-8"))
    return datetime.fromisoformat(
        incident["timestamps"]["fault_start"].replace("Z", "+00:00")).timestamp()


# 方法说明：_score 返回窗口是否 PASS。
def _score(window, detector):
    return detector.decide(window["rows"])["decision"] == "PASS"


# 方法说明：main 训练并评测统一窗口。
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True)
    parser.add_argument("--source-type", choices=("docker_container", "wsl"), required=True)
    parser.add_argument("--normal-dir", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--diagnosis", default=None)
    parser.add_argument("--window-seconds", type=int, default=60)
    parser.add_argument("--window-step", type=int, default=10)
    parser.add_argument("--max-rows", type=int, default=500)
    parser.add_argument("--target-fpr", type=float, default=0.05)
    parser.add_argument("--save", default=None)
    args = parser.parse_args(argv)
    normal = load_normal_windows(args.normal_dir, args.source_type,
                                 duration_seconds=args.window_seconds,
                                 step_seconds=args.window_step,
                                 max_rows=args.max_rows)
    split = int(len(normal) * 0.7)
    train_normal, test_normal = normal[:split], normal[split:]
    detector = TemplateNoveltyDetector(args.target_fpr).fit(
        [window["rows"] for window in train_normal])
    test_fp = sum(1 for window in test_normal if _score(window, detector))
    top1 = {}
    if args.diagnosis and Path(args.diagnosis).is_file():
        rows = json.loads(Path(args.diagnosis).read_text(encoding="utf-8"))["rows"]
        top1 = {row["incident_id"]: bool(row.get("top1")) for row in rows}
    cases = [case for case in sorted(Path(args.cases).glob("*"))
             if (case / "incident.json").is_file()]
    fault_windows = detected_windows = detected_cases = e2e_hits = 0
    for case in cases:
        windows = load_case_windows(case, args.source_type,
                                    duration_seconds=args.window_seconds,
                                    step_seconds=args.window_step,
                                    max_rows=args.max_rows)
        start = _fault_start(case)
        fault = [window for window in windows if window["end"] > start]
        if not fault:
            continue
        fault_windows += len(fault)
        passed = [window for window in fault if _score(window, detector)]
        detected_windows += len(passed)
        hit = bool(passed)
        detected_cases += int(hit)
        if hit and top1.get(case.name, False):
            e2e_hits += 1
    result = {
        "source_type": args.source_type, "window_seconds": args.window_seconds,
        "window_step": args.window_step, "max_rows": args.max_rows,
        "model": "severity_first_novelty",
        "normal_windows": len(normal), "train_normal": len(train_normal),
        "test_normal": len(test_normal), "fault_windows": fault_windows,
        "detected_fault_windows": detected_windows,
        "window_recall": round(detected_windows / fault_windows, 4) if fault_windows else None,
        "normal": {"false_positive": test_fp, "fpr":
                   round(test_fp / len(test_normal), 4) if test_normal else None,
                   "fpr_ci": wilson(test_fp, len(test_normal))},
        "cases": len(cases), "detected_cases": detected_cases,
        "case_recall": round(detected_cases / len(cases), 4) if cases else None,
        "end_to_end": {"cases": len(cases), "hits": e2e_hits,
                       "top1": round(e2e_hits / len(cases), 4) if cases else None,
                       "top1_ci": wilson(e2e_hits, len(cases))},
        "threshold": detector.threshold,
    }
    if args.save:
        detector.fit([window["rows"] for window in normal]).save(args.save)
        result["saved"] = str(args.save)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
