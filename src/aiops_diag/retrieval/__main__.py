import argparse
import json

from .config import load
from .release import FrozenRetriever, verify
from .workflow import benchmark, build, fetch_model, finalize, publish, tune, validate


def main(argv=None):
    parser = argparse.ArgumentParser(description="W7 reproducible hybrid retrieval")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "fetch-model", "build", "tune", "publish", "finalize", "verify", "benchmark"):
        item = sub.add_parser(name); item.add_argument("--config", required=True)
    search = sub.add_parser("search")
    search.add_argument("--config", required=True); search.add_argument("--query", required=True)
    search.add_argument("--mode", choices=("frozen", "bm25", "dense", "hybrid"), default="frozen")
    search.add_argument("--top-k", type=int, default=None)
    args = parser.parse_args(argv)
    cfg = load(args.config)
    commands = {"validate": validate, "fetch-model": fetch_model, "build": build,
                "tune": tune, "publish": publish, "finalize": finalize, "verify": verify,
                "benchmark": benchmark}
    if args.command == "search":
        result = FrozenRetriever(cfg).search(args.query, mode=args.mode, top_k=args.top_k)
    else:
        result = commands[args.command](cfg)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
