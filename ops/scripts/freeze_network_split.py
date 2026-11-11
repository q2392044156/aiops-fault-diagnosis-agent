"""脚本说明：为网络分区单独冻结 train/test 切分。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


# 方法说明：main 生成按稳定哈希分层的网络分区切分。
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--test-ratio", type=float, default=0.3)
    args = parser.parse_args(argv)
    cases = []
    for path in sorted(Path(args.cases).glob("*")):
        if not (path / "incident.json").is_file():
            continue
        incident = json.loads((path / "incident.json").read_text(encoding="utf-8"))
        cases.append({"incident_id": incident["incident_id"],
                      "root_cause_code": incident["labels"]["root_cause_code"]})
    ranked = sorted(cases, key=lambda row: hashlib.sha256(
        row["incident_id"].encode("utf-8")).hexdigest())
    test_count = max(1, round(len(ranked) * args.test_ratio))
    test = ranked[:test_count]
    train = ranked[test_count:]
    payload = {"dataset": "network_partition", "split": "frozen_hash",
               "test": [row["incident_id"] for row in test],
               "train": [row["incident_id"] for row in train],
               "test_count": len(test), "train_count": len(train),
               "test_ratio": args.test_ratio}
    payload["split_hash"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("test_count", "train_count", "split_hash")},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
