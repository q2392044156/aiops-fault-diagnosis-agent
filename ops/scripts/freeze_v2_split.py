"""脚本说明：冻结 v2 的批次/分层切分。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


# _cases 读取案例 ID 与故障族。
def _cases(directory, prefix=None):
    rows = []
    for case in sorted(Path(directory).glob("*")):
        if not (case / "incident.json").is_file():
            continue
        incident = json.loads((case / "incident.json").read_text(encoding="utf-8"))
        if prefix and not case.name.startswith(prefix):
            continue
        rows.append({"incident_id": incident["incident_id"],
                     "source": "wsl" if "wsl" in str(directory) else "docker",
                     "family": incident.get("fault_family")})
    return rows


# main 生成 train/test 并冻结哈希。
def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--docker", required=True)
    parser.add_argument("--wsl", required=True)
    parser.add_argument("--recaptured", required=True)
    args = parser.parse_args(argv)
    bad = set(json.loads(Path(args.manifest).read_text(encoding="utf-8"))["quarantined_docker"])
    docker = [row for row in _cases(args.docker) if row["incident_id"] not in bad]
    wsl = _cases(args.wsl)
    recaptured = _cases(args.recaptured, prefix="inc_wsl_volume")
    test = recaptured[:]
    # 补 9 个旧批次分层样本：Docker 3、WSL 6，按哈希稳定选择。
    for source_rows, count in ((docker, 3), (wsl, 6)):
        ranked = sorted(source_rows, key=lambda row: hashlib.sha256(
            row["incident_id"].encode("utf-8")).hexdigest())
        test.extend(ranked[:count])
    test_ids = {row["incident_id"] for row in test}
    train = [row for row in docker + wsl + recaptured
             if row["incident_id"] not in test_ids]
    payload = {"dataset": "merged_v2", "split": "batch_stratified",
               "seed": "sha256(incident_id)",
               "test": sorted(test_ids), "train": sorted(row["incident_id"] for row in train),
               "test_count": len(test_ids), "train_count": len(train),
               "test_sources": {"docker": sum(1 for row in test if row["source"] == "docker"),
                                "wsl": sum(1 for row in test if row["source"] == "wsl")},
               "test_families": {family: sum(1 for row in test if row["family"] == family)
                                 for family in sorted({row["family"] for row in test})}}
    payload["split_hash"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    Path(args.output).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("test_count", "train_count",
                                             "test_sources", "test_families", "split_hash")},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
