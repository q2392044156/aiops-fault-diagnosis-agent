import argparse
import json
import sys
from pathlib import Path

import yaml

from .audit import audit
from .common import config
from .download import download
from .incident_v12 import (audit_incident, delete_incident, import_incident,
                           load_incident, validate_incident)
from .pipeline import build, split, subset, trace
from .v12_external import (DEFAULT_SEED, audit_external_outputs,
                           prepare_external_datasets)
from .v12_import import import_snapshots
from aiops_diag.service.db import Database


def _legacy(argv):
    parser = argparse.ArgumentParser(description="W1 HDFS data preparation")
    parser.add_argument("command", choices=["download", "build", "split", "subset", "audit", "trace"])
    parser.add_argument("--config", default="configs/data.yaml")
    parser.add_argument("--log-id")
    args = parser.parse_args(argv)
    cfg = config(args.config)
    if args.command == "trace":
        if not args.log_id:
            parser.error("trace requires --log-id")
        return trace(cfg, args.log_id)
    return {"download": download, "build": build, "split": split,
            "subset": subset, "audit": audit}[args.command](cfg)


def _external(argv):
    parser = argparse.ArgumentParser(description="v1.2 public dataset workflow")
    parser.add_argument("command", choices=["prepare", "audit", "import-service"])
    parser.add_argument("--config", default="configs/data_v12_external.yaml")
    parser.add_argument("--source-root")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--split", choices=["development", "calibration", "independent_test"])
    parser.add_argument("--database")
    parser.add_argument("--artifact-root")
    args = parser.parse_args(argv)
    config_path = Path(args.config).resolve()
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    root = config_path.parent.parent
    source = Path(args.source_root).resolve() if args.source_root else (
        root / raw.get("source_root", "data/external/loghub")).resolve()
    if args.command == "prepare":
        return prepare_external_datasets(source, args.seed or int(raw.get("seed", DEFAULT_SEED)))
    if args.command == "audit":
        return audit_external_outputs(source)
    if not args.split or not args.database or not args.artifact_root:
        parser.error("import-service requires --split, --database and --artifact-root")
    db = Database(args.database)
    db.init()
    return import_snapshots(
        db, source / "processed/diagnostic_snapshots.jsonl",
        source / "processed/evaluation_labels.jsonl", args.split, args.artifact_root)


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
