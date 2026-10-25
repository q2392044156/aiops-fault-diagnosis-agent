"""模块说明：实现 `python -m` 命令行入口和参数分发。"""

import argparse
import json

from .config import load
from .workflow import accept, export, freeze, verify


# 方法说明：`main` 完成当前步骤的业务处理；参数为 `argv`。
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
