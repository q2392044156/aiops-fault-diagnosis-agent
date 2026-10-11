import argparse
import json
import time

import httpx


SAMPLE = (
    b"081109 203518 143 INFO dfs.DataNode$DataXceiver: Receiving block blk_-1 "
    b"src: /10.0.0.1:1\n"
    b"081109 203519 144 ERROR dfs.DataNode$DataXceiver: Failed block blk_-1 "
    b"at /10.0.0.1:1\n"
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--registered-id")
    args = parser.parse_args()
    client = httpx.Client(base_url=args.base_url, timeout=30, trust_env=False)
    ready = client.get("/api/v1/health/ready"); ready.raise_for_status()
    release = client.get("/api/v1/releases/current"); release.raise_for_status()
    if args.registered_id:
        submitted = client.post(
            "/api/v1/batches/registered", json={"registered_id": args.registered_id},
            headers={"Idempotency-Key": f"w6-registered-{args.registered_id}-v1"},
        )
    else:
        submitted = client.post(
            "/api/v1/batches/uploads",
            files={"file": ("w6-smoke.log", SAMPLE, "text/plain")},
            headers={"Idempotency-Key": "w6-container-smoke-v1"},
        )
    submitted.raise_for_status()
    task = submitted.json()
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        response = client.get(task["links"]["self"]); response.raise_for_status()
        task = response.json()
        if task["status"] in ("SUCCEEDED", "FAILED"):
            break
        time.sleep(0.2)
    if task["status"] != "SUCCEEDED":
        raise SystemExit(f"Smoke task did not succeed: {task}")
    events = client.get("/api/v1/events", params={"batch_id": task["batch_id"]})
    events.raise_for_status()
    operations = client.get("/api/v1/operations/summary"); operations.raise_for_status()
    result = {
        "ready": ready.json(), "release": release.json(), "task": task,
        "event_count": len(events.json()["items"]), "operations": operations.json(),
    }
    if events.json()["items"]:
        detail = client.get(f"/api/v1/events/{events.json()['items'][0]['event_id']}")
        detail.raise_for_status()
        session = detail.json()["sessions"][0]
        logs = client.get(
            f"/api/v1/batches/{task['batch_id']}/logs",
            params={"session_id": session["session_id"], "limit": 20},
        )
        logs.raise_for_status()
        result["log_count"] = len(logs.json()["items"])
        if any("10.0.0.1" in row["redacted_message"] for row in logs.json()["items"]):
            raise SystemExit("Raw IPv4 address escaped redaction")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
