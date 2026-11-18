"""v1.2 授权事件生命周期：校验、导入、审计与删除。"""

import argparse

from aiops_diag.platform.db import Database
from offline.case.incident import audit_incident, delete_incident, import_incident, load_incident, validate_incident


def run(argv):
    """解析参数并执行一条 incident 子命令，返回可序列化的结果。"""
    parser = argparse.ArgumentParser(prog="python -m aiops_diag.platform incident",
                                     description="v1.2 authorized incident lifecycle")
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
