"""
数据准备工具
"""
import argparse
import json
import sys
from pathlib import Path

import yaml

from .audit import audit
from .common import config, config_root
from .download import download
from .incident_v12 import (audit_incident, delete_incident, import_incident,
                           load_incident, validate_incident)
from .pipeline import build, split, subset, trace
from aiops_diag.platform.db import Database

# 主入口函数, 根据命令行参数调用不同的数据准备功能
def _legacy(argv):
    parser = argparse.ArgumentParser(description="W1 HDFS data preparation")
    parser.add_argument("command", choices=["download", "build", "split", "subset", "audit", "trace"])
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


# 方法说明：`_incident` 完成当前步骤的业务处理；参数为 `argv`。
def _incident(argv):
    parser = argparse.ArgumentParser(description="v1.2 authorized incident lifecycle")
    parser.add_argument("command", choices=["validate", "import", "audit", "delete"])
    parser.add_argument("target", nargs="?")
    parser.add_argument("--input")
    parser.add_argument("--incident-id")
    parser.add_argument("--database")
    parser.add_argument("--reason")
    args = parser.parse_args(argv)
    explicit = args.input if args.command in ("validate", "import") else args.incident_id
    if args.target and explicit:
        parser.error("provide the target either positionally or by named option, not both")
    target = args.target or explicit
    if not target:
        option = "--input" if args.command in ("validate", "import") else "--incident-id"
        parser.error(f"{args.command} requires a target or {option}")
    if args.command == "validate":
        return validate_incident(load_incident(target))
    if not args.database:
        parser.error(f"{args.command} requires --database")
    db = Database(args.database)
    db.init()
    if args.command == "import":
        return import_incident(db, target)
    if args.command == "audit":
        return audit_incident(db, target)
    if not args.reason:
        parser.error("delete requires --reason")
    return delete_incident(db, target, args.reason)


# 方法说明：`main` 完成当前步骤的业务处理；参数为 `argv`。
def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if argv and argv[0] == "v12-external":
            result = _external(argv[1:])
        elif argv and argv[0] == "incident":
            result = _incident(argv[1:])
        else:
            result = _legacy(argv)
        print(json.dumps(result, ensure_ascii=False, default=str, indent=2))
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
