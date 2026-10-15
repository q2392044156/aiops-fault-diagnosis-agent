import argparse
import json

from .config import load
from .workflow import accept, export, freeze, verify


def main(argv=None):
    parser = argparse.ArgumentParser(description="W10 v1.0 release acceptance")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("freeze", "verify", "accept", "export"):
        item = sub.add_parser(name)
        item.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    cfg = load(args.config)
    value = {"freeze": freeze, "verify": verify, "accept": accept, "export": export}[
        args.command](cfg)
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
