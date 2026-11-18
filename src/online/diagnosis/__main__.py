"""实现 `python -m` 命令行入口和参数分发。"""

import argparse
import json

from online.diagnosis.auth import initialize_reviewer
from online.diagnosis.release import publish, verify
from online.diagnosis.settings import load


def main(argv=None):
    parser = argparse.ArgumentParser(description="W9 controlled diagnosis agent")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("publish", "verify"):
        item = sub.add_parser(name)
        item.add_argument("--config", required=True)
    init = sub.add_parser("init-reviewer")
    init.add_argument("--reviewer-id", default="local-reviewer")
    init.add_argument("--registry", required=True)
    init.add_argument("--token-file", required=True)
    args = parser.parse_args(argv)
    if args.command == "init-reviewer":
        value = initialize_reviewer(args.registry, args.token_file, args.reviewer_id)
        print(json.dumps({"reviewer_id": value["reviewer_id"],
                          "registry": value["registry"],
                          "token_file": value["token_file"],
                          "token_sha256": value["token_sha256"]},
                         ensure_ascii=False, indent=2))
        return
    cfg = load(args.config)
    if args.command == "publish":
        print(json.dumps(publish(cfg), ensure_ascii=False, indent=2))
    elif args.command == "verify":
        print(json.dumps(verify(cfg), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
