import argparse
import json
from pathlib import Path

import yaml

from aiops_diag.data.v12_external import DEFAULT_SEED, prepare_external_datasets


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare public Hadoop/TraceBench data for v1.2")
    parser.add_argument("--config", type=Path, default=Path("configs/data_v12_external.yaml"))
    parser.add_argument(
        "--source-root",
        type=Path,
        default=None,
        help="Directory containing verified Hadoop and HDFS_v3_TraceBench archives/directories",
    )
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()
    config = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    project_root = args.config.resolve().parent.parent
    source_root = args.source_root or project_root / config.get("source_root", "data/external/loghub")
    seed = args.seed if args.seed is not None else int(config.get("seed", DEFAULT_SEED))
    result = prepare_external_datasets(source_root, seed=seed)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
