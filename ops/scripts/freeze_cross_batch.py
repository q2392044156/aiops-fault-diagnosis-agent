"""脚本说明：冻结网络分区+磁盘 IO 的跨批次测试集。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


# main 合并两个独立测试集并冻结。
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--network-split", required=True)
    parser.add_argument("--disk-split", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    network = json.loads(Path(args.network_split).read_text(encoding="utf-8"))
    disk = json.loads(Path(args.disk_split).read_text(encoding="utf-8"))
    payload = {"dataset": "cross_batch_network_disk", "split": "frozen_batch",
               "network_test": network["test"], "disk_test": disk["test"],
               "test_count": len(network["test"]) + len(disk["test"])}
    payload["split_hash"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("test_count", "split_hash")},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
