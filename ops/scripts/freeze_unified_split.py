"""脚本说明：按故障族+来源冻结统一 train/test 切分。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


# _pick 按稳定哈希选择测试案例。
def _pick(rows, count):
    ranked = sorted(rows, key=lambda row: hashlib.sha256(
        row["case_id"].encode("utf-8")).hexdigest())
    return ranked[:count]


# main 生成统一 train/test 切分。
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--test-per-class", type=int, default=15)
    args = parser.parse_args(argv)
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    test, train = [], []
    for family in sorted({row["family"] for row in manifest["cases"]}):
        rows = [row for row in manifest["cases"] if row["family"] == family]
        groups = {}
        for row in rows:
            groups.setdefault(row["source"], []).append(row)
        target = min(args.test_per_class, len(rows) - 1)
        allocation = {}
        for source, group in groups.items():
            allocation[source] = max(1, round(target * len(group) / len(rows)))
        while sum(allocation.values()) > target:
            source = max(allocation, key=allocation.get)
            if allocation[source] > 1:
                allocation[source] -= 1
            else:
                break
        while sum(allocation.values()) < target:
            source = max(groups, key=lambda name: len(groups[name]) - allocation[name])
            allocation[source] += 1
        selected = []
        for source, group in groups.items():
            selected.extend(_pick(group, allocation[source]))
        selected_ids = {row["case_id"] for row in selected}
        test.extend(row["case_id"] for row in selected)
        train.extend(row["case_id"] for row in rows if row["case_id"] not in selected_ids)
    payload = {"dataset": manifest.get("dataset", "unified_4_fault"),
               "split": "stratified_by_family_source",
               "test_per_class": args.test_per_class,
               "test": sorted(test), "train": sorted(train),
               "test_count": len(test), "train_count": len(train)}
    payload["split_hash"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("test_count", "train_count", "split_hash")},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
