import argparse
import json
import sys

from .config import load
from .workflow import (ablate, compare_parsing, finalize, inspect,
                       preregister, report, run)


def main():
    parser = argparse.ArgumentParser(description="W4 model selection and frozen evaluation")
    parser.add_argument("command", choices=["preregister", "compare-parsing", "ablate",
                                            "finalize", "report", "inspect", "run"])
    parser.add_argument("--config", default="configs/model_selection.yaml")
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    parser.add_argument("--model-id")
    parser.add_argument("--session-id")
    args = parser.parse_args()
    try:
        cfg = load(args.config)
        if args.command == "preregister":
            result = preregister(cfg)
        elif args.command == "compare-parsing":
            result = compare_parsing(cfg)
        elif args.command == "ablate":
            result = ablate(cfg, args.device)
        elif args.command == "finalize":
            result = finalize(cfg, args.device)
        elif args.command == "report":
            result = report(cfg)
        elif args.command == "inspect":
            if not args.model_id or not args.session_id:
                parser.error("inspect requires --model-id and --session-id")
            result = inspect(cfg, args.model_id, args.session_id)
        else:
            result = run(cfg, args.device)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
