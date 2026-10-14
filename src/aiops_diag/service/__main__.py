import argparse
import json
import logging

import uvicorn

from .api import create_app
from .benchmark import run as run_benchmark
from .config import load
from .release import FrozenRelease, publish, verify
from .runtime import ServiceRuntime


def main(argv=None):
    parser = argparse.ArgumentParser(description="W8 container-ready anomaly and knowledge service")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("publish", "init", "verify", "serve", "worker", "worker-health"):
        item = sub.add_parser(name)
        item.add_argument("--config", required=True)
    benchmark = sub.add_parser("benchmark")
    benchmark.add_argument("--config", required=True)
    benchmark.add_argument("--suite", choices=("e1", "e2", "e3", "e4", "all"),
                           default="all")
    args = parser.parse_args(argv)
    cfg = load(args.config)
    if args.command == "publish":
        print(json.dumps(publish(cfg), ensure_ascii=False, indent=2))
    elif args.command == "init":
        runtime = ServiceRuntime(cfg, load_model=False)
        print(json.dumps({"database": str(runtime.db.path), "schema_version": 3},
                         ensure_ascii=False, indent=2))
    elif args.command == "verify":
        manifest = verify(cfg)
        FrozenRelease(cfg)
        print(json.dumps({"verified": True, "release_id": manifest["release_id"],
                          "model_id": manifest["model_id"]}, ensure_ascii=False, indent=2))
    elif args.command == "serve":
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        app = create_app(cfg)
        uvicorn.run(app, host=cfg["server"]["host"], port=int(cfg["server"]["port"]),
                    workers=1, log_level="info")
    elif args.command == "worker":
        logging.basicConfig(level=logging.INFO, format="%(message)s")
        runtime = ServiceRuntime(cfg, load_model=True, role="worker")
        if runtime.ready_error:
            raise SystemExit(runtime.ready_error)
        try:
            runtime.run_forever()
        except KeyboardInterrupt:
            runtime.stop()
    elif args.command == "worker-health":
        runtime = ServiceRuntime(cfg, load_model=False, role="healthcheck")
        if runtime.manifest is None:
            raise SystemExit(runtime.ready_detail or "release unavailable")
        age = int(cfg["worker"].get("heartbeat_max_age_seconds", 15))
        if runtime.db.worker_ready(runtime.manifest["release_id"], age) is None:
            raise SystemExit("worker heartbeat is stale")
        print("ready")
    elif args.command == "benchmark":
        print(json.dumps(run_benchmark(cfg, args.suite), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
