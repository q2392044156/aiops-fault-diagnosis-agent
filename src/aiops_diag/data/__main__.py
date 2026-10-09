import argparse
import json
import sys

from .common import config
from .download import download
from .pipeline import build, split, subset, trace
from .audit import audit


def main():
    p = argparse.ArgumentParser(description="W1 HDFS data preparation")
    p.add_argument("command", choices=["download", "build", "split", "subset", "audit", "trace"])
    p.add_argument("--config", default="configs/data.yaml")
    p.add_argument("--log-id")
    args = p.parse_args()
    try:
        c = config(args.config)
        if args.command == "trace":
            if not args.log_id:
                p.error("trace requires --log-id")
            result = trace(c, args.log_id)
        else:
            result = {"download": download, "build": build, "split": split, "subset": subset, "audit": audit}[args.command](c)
        print(json.dumps(result, ensure_ascii=False, default=str, indent=2))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
