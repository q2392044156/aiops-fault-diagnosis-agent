import argparse
import json

from aiops_diag.rag.client import DeepSeekClient
from aiops_diag.service.config import load as load_service_config
from aiops_diag.service.db import Database

from .auth import initialize_reviewer
from .budget import DatabaseBudgetLedger
from .config import load
from .release import publish, verify
from .workflow import evaluate


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
    run_eval = sub.add_parser("evaluate")
    run_eval.add_argument("--config", required=True)
    run_eval.add_argument("--online", action="store_true")
    run_eval.add_argument("--suite", choices=("adev", "atest"), default="adev")
    run_eval.add_argument("--mode", choices=("replay", "online"))
    run_eval.add_argument("--repeat", type=int, default=1)
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
    elif args.command == "evaluate":
        online = args.online or args.mode == "online"
        client = None
        if online:
            service_cfg = load_service_config(cfg["service_config_path"])
            database = Database(service_cfg["paths"]["database"])
            database.init()
            ledger = DatabaseBudgetLedger(
                database, cfg["rag"]["provider"]["name"], cfg["rag"]["budget"],
                cfg["rag"]["paths"].get("budget_ledger"), scope=f"w10_{args.suite}")
            client = DeepSeekClient(cfg["rag"], ledger=ledger)
        try:
            value = evaluate(cfg, online=online, client=client,
                             suite=args.suite, repeat=args.repeat)
        finally:
            if client:
                client.close()
        if "runs" in value:
            shown = {name: value[name] for name in (
                "suite", "mode", "requested_repeats", "completed_repeats", "aggregate")}
        else:
            shown = {name: value[name] for name in (
                "suite", "cases", "terminal_accuracy", "task_success_rate",
                "mandatory_review_recall", "review_precision", "schema_pass_rate",
                "citation_valid_rate", "template_fallback_rate", "online_calls",
                "elapsed_ms")}
        print(json.dumps(shown, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
