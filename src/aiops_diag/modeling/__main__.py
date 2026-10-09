import argparse
import json
import sys
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq

from aiops_diag.data.common import verified_manifest
from .config import load
from .evaluation import evaluate
from .models import predictions, train
from .protocol import freeze
from .templates import build_templates


def inspect(cfg, run_id, session_id):
    base = Path(cfg["experiment_dir"])
    run_dir = (base / run_id).resolve()
    if run_dir.parent != base.resolve():
        raise ValueError("Invalid run ID")
    training = verified_manifest(run_dir, "training.json")
    if training["run_id"] != run_id:
        raise ValueError("Run ID does not match registered manifest")
    table = pq.read_table(run_dir / "predictions.parquet")
    selected = table.filter(pc.equal(table["block_id"], session_id)).to_pylist()
    if not selected:
        raise ValueError("Validation session not found in this run")
    row = selected[0]
    vocab = json.loads((Path(cfg["artifact_dir"]) / "template_vocab.json").read_text(encoding="utf-8"))
    row["templates"] = [{"template_id": value, "template": vocab.get(str(value))}
                        for value in row["template_ids"]]
    row["raw_log_refs"] = {"first": row["first_log_id"], "last": row["last_log_id"]}
    return row


def main():
    parser = argparse.ArgumentParser(description="W2 frozen parsing and anomaly baselines")
    parser.add_argument("command", choices=["freeze", "templates", "train", "predict",
                                            "evaluate", "run", "inspect"])
    parser.add_argument("--config", default="configs/model_lr.yaml")
    parser.add_argument("--split", default="validation")
    parser.add_argument("--run-id")
    parser.add_argument("--session-id")
    args = parser.parse_args()
    try:
        cfg = load(args.config)
        if args.command == "freeze":
            result = freeze(cfg)
        elif args.command == "templates":
            freeze(cfg)
            result = build_templates(cfg)
        elif args.command == "train":
            freeze(cfg); build_templates(cfg)
            result = train(cfg)
        elif args.command == "predict":
            freeze(cfg); build_templates(cfg)
            result = predictions(cfg, args.split)
        elif args.command == "evaluate":
            freeze(cfg); build_templates(cfg)
            result = evaluate(cfg, args.split)
        elif args.command == "run":
            freeze_result = freeze(cfg)
            template_result = build_templates(cfg)
            training_result = train(cfg)
            evaluation_result = evaluate(cfg, "validation")
            result = {"freeze": freeze_result, "templates": template_result,
                      "training": training_result, "evaluation": evaluation_result}
        else:
            if not args.run_id or not args.session_id:
                parser.error("inspect requires --run-id and --session-id")
            result = inspect(cfg, args.run_id, args.session_id)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
