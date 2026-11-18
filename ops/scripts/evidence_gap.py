"""脚本说明：审计证据不足案例，给出补采集清单。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")
sys.path.insert(0, "ops/lab/harness")
sys.path.insert(0, "ops/scripts")
from evaluate_evidence import _rows

from online.diagnosis.agent import evidence_sufficiency, select_log_rows


# main 输出证据不足案例。
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True)
    parser.add_argument("--source-type", choices=("docker_container", "wsl"), required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    gaps = []
    for case in sorted(Path(args.cases).glob("*")):
        if not (case / "incident.json").is_file():
            continue
        incident, rows = _rows(case, args.source_type)
        selected = select_log_rows(rows, 50, 2000)
        quality = evidence_sufficiency(selected)
        if not quality["sufficient"]:
            gaps.append({"incident_id": incident["incident_id"],
                         "lines": len(rows), "selected": len(selected),
                         "root_cause_code": incident["labels"]["root_cause_code"],
                         "missing": quality["missing"],
                         "recommendation": "补采 fault_start-60s 到 cutoff+60s 的 NN/DN 日志"})
    Path(args.output).write_text(json.dumps({"cases": len(gaps), "gaps": gaps},
                                            ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    print(json.dumps({"cases": len(gaps), "incidents": [g["incident_id"] for g in gaps]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
