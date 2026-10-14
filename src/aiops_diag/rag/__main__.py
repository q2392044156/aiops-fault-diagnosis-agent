import argparse
import json

from .config import load
from .engine import RagEngine
from .release import verify
from .workflow import benchmark, fetch_reranker, finalize, publish, tune, validate


def main(argv=None):
    parser = argparse.ArgumentParser(description="W8 evidence-grounded knowledge report generation")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "reranker", "tune", "finalize", "publish", "verify", "benchmark"):
        item = sub.add_parser(name)
        item.add_argument("--config", required=True)
    generate = sub.add_parser("generate")
    generate.add_argument("--config", required=True)
    generate.add_argument("--query", required=True)
    generate.add_argument("--mode", choices=("auto", "template"), default="auto")
    args = parser.parse_args(argv)
    cfg = load(args.config)
    commands = {"validate": validate, "reranker": fetch_reranker, "tune": tune,
                "finalize": finalize, "publish": publish, "verify": verify,
                "benchmark": benchmark}
    if args.command == "generate":
        engine = RagEngine(cfg)
        try:
            result = engine.generate(args.query, mode=args.mode).model_dump()
        finally:
            engine.close()
    else:
        result = commands[args.command](cfg)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
