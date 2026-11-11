"""脚本说明：构建 5 类故障的统一 manifest。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

# 变量说明：FAMILIES 映射根因码到故障族名称。
FAMILIES = {
    "DN_VOLUME": "volume", "DN_HEARTBEAT": "heartbeat",
    "NN_SAFE_MODE": "safe_mode", "NETWORK_CONNECTIVITY": "network",
    "DISK_IO": "disk_io",
}


# 方法说明：_rows 读取一个批次目录的案例。
def _rows(directory, batch, bad=None):
    rows = []
    for case in sorted(Path(directory).glob("*")):
        incident = case / "incident.json"
        if not incident.is_file():
            continue
        value = json.loads(incident.read_text(encoding="utf-8"))
        case_id = value["incident_id"]
        if bad and case_id in bad:
            continue
        code = value["labels"]["root_cause_code"]
        rows.append({"case_id": case_id, "path": str(case), "batch": batch,
                     "source": "wsl" if batch in ("wsl", "recaptured", "disk_io") else "docker",
                     "root_cause_code": code, "family": FAMILIES.get(code, code.lower())})
    return rows


# 方法说明：main 构建并写出统一 manifest。
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    base = Path(args.root)
    bad = set(json.loads((base / "resources/evaluation/lab/recaptured_manifest.json")
                         .read_text(encoding="utf-8"))["quarantined_docker"])
    rows = []
    rows += _rows(base / "ops/lab/real_batch_cases", "docker", bad)
    rows += _rows(base / "ops/lab/wsl_cases", "wsl")
    rows += _rows(base / "ops/lab/recaptured_cases/wsl_volume", "recaptured")
    rows += _rows(base / "ops/lab/network_cases", "network")
    rows += _rows(base / "ops/lab/disk_io_cases", "disk_io")
    payload = {"dataset": "unified_5_fault", "case_count": len(rows),
               "classes": {name: sum(1 for row in rows if row["family"] == name)
                           for name in FAMILIES.values()},
               "cases": rows}
    payload["manifest_hash"] = hashlib.sha256(
        json.dumps(rows, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("case_count", "classes", "manifest_hash")},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
