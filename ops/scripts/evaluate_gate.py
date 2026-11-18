"""脚本说明：用正常/故障窗口评测门禁，并给出端到端指标。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")
sys.path.insert(0, "ops/lab/harness")
from windows import load_windows

from aiops_diag.platform.events import score_rows


# _quantile 返回分位数。
def _quantile(values, q):
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, int(len(values) * q))]


# _metrics 计算给定阈值下的 FPR/Recall。
def _metrics(normal, fault, threshold):
    false_positive = sum(1 for score in normal if score >= threshold)
    hits = sum(1 for score in fault if score >= threshold)
    return {"threshold": threshold,
            "normal": len(normal), "false_positive": false_positive,
            "fpr": round(false_positive / len(normal), 4) if normal else None,
            "fault": len(fault), "detected": hits,
            "recall": round(hits / len(fault), 4) if fault else None}


# main 扫描案例并输出门禁评测。
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True)
    parser.add_argument("--source-type", choices=("docker_container", "wsl"), default=None)
    parser.add_argument("--output", required=True)
    parser.add_argument("--baseline", type=float, default=0.6)
    args = parser.parse_args(argv)
    normal, fault = [], []
    for case in sorted(Path(args.cases).glob("*")):
        if not (case / "incident.json").is_file():
            continue
        window = load_windows(case, args.source_type)
        if not window:
            continue
        if window["normal"]:
            normal.append(score_rows(window["normal"]))
        if window["fault"]:
            fault.append(score_rows(window["fault"]))
    adjusted = max(args.baseline, _quantile(normal, 0.95) or 0.0)
    result = {"baseline": _metrics(normal, fault, args.baseline),
              "calibrated": _metrics(normal, fault, adjusted)}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
