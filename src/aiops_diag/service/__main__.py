import argparse
import json

import uvicorn

from .api import create_app
from .config import load
from .release import FrozenRelease, publish, verify
from .runtime import ServiceRuntime


def main(argv=None):
    parser = argparse.ArgumentParser(description="W5 durable anomaly-detection service")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("publish", "init", "verify", "serve"):
        item = sub.add_parser(name)
        item.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    cfg = load(args.config)
    if args.command == "publish":
        print(json.dumps(publish(cfg), ensure_ascii=False, indent=2))
    elif args.command == "init":
        runtime = ServiceRuntime(cfg, load_model=False)
        print(json.dumps({"database": str(runtime.db.path), "schema_version": 1},
                         ensure_ascii=False, indent=2))
    elif args.command == "verify":
        manifest = verify(cfg)
        FrozenRelease(cfg)
        print(json.dumps({"verified": True, "release_id": manifest["release_id"],
                          "model_id": manifest["model_id"]}, ensure_ascii=False, indent=2))
    elif args.command == "serve":
        app = create_app(cfg)
        uvicorn.run(app, host=cfg["server"]["host"], port=int(cfg["server"]["port"]),
                    workers=1, log_level="info")


if __name__ == "__main__":
    main()
