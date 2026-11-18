"""
数据准备命令集：下载、构建、切分、抽样、审计与追踪。
"""

import argparse
import json
import sys

from aiops_diag.common import config

from .audit import audit
from .download import download
from .pipeline import build, split, subset, trace


def _legacy(argv):
    parser = argparse.ArgumentParser(description="W1 HDFS data preparation")
    parser.add_argument("command",
                        choices=["download", "build", "split", "subset", "audit", "trace"])
    parser.add_argument("--config", default="resources/configs/data.yaml")
    parser.add_argument("--log-id")
    args = parser.parse_args(argv)
    cfg = config(args.config)
    if args.command == "trace":
        if not args.log_id:
            parser.error("trace requires --log-id")
        return trace(cfg, args.log_id)
    return {"download": download, "build": build, "split": split,
            "subset": subset, "audit": audit}[args.command](cfg)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        result = _legacy(argv)
        print(json.dumps(result, ensure_ascii=False, default=str, indent=2))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
