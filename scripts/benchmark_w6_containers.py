import argparse
import json
import subprocess
import time
from pathlib import Path

import httpx


def wait_ready(timeout):
    client = httpx.Client(timeout=2, trust_env=False)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            api = client.get("http://127.0.0.1:8000/api/v1/health/ready")
            ui = client.get("http://127.0.0.1:8501/_stcore/health")
            if api.status_code == 200 and ui.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise TimeoutError("W6 containers did not become ready before the timeout")


def compose(root, *args):
    subprocess.run(
        ["docker", "compose", "-f", "deployment/compose.yaml", *args],
        cwd=root, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=90)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    results = {"schema_version": 1, "cold_seconds": [], "hot_seconds": []}
    for _ in range(args.repetitions):
        compose(root, "down")
        started = time.perf_counter()
        compose(root, "up", "-d")
        wait_ready(args.timeout)
        results["cold_seconds"].append(time.perf_counter() - started)
    for _ in range(args.repetitions):
        started = time.perf_counter()
        compose(root, "restart", "worker", "api", "ui")
        wait_ready(args.timeout)
        results["hot_seconds"].append(time.perf_counter() - started)
    target = root / "experiments" / "w6" / "container_startup.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
