import argparse
import hashlib
import json
import time
from pathlib import Path

import httpx


def wait_for(client, path, terminal, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(path)
        response.raise_for_status()
        value = response.json()
        if value["status"] in terminal:
            return value
        time.sleep(0.2)
    raise TimeoutError(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:18000")
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--reviewer-token-file")
    parser.add_argument("--mode", choices=("auto", "template"), default="template")
    parser.add_argument("--event-index", type=int, default=0)
    parser.add_argument("--id-suffix", default="v1")
    args = parser.parse_args()
    client = httpx.Client(base_url=args.base_url, timeout=30, trust_env=False)

    submitted = client.post(
        "/api/v1/batches/registered",
        json={"registered_id": "w1_dev"},
        headers={"Idempotency-Key": f"w10-acceptance-registered-{args.id_suffix}"},
    )
    submitted.raise_for_status()
    task = wait_for(client, submitted.json()["links"]["self"],
                    {"SUCCEEDED", "FAILED"}, args.timeout)
    if task["status"] != "SUCCEEDED":
        raise RuntimeError(task)
    events = client.get("/api/v1/events", params={"batch_id": task["batch_id"]})
    events.raise_for_status()
    event = events.json()["items"][args.event_index]

    submitted = client.post(
        "/api/v1/diagnoses",
        json={"event_id": event["event_id"], "mode": args.mode},
        headers={"Idempotency-Key": f"w10-acceptance-diagnosis-{args.id_suffix}"},
    )
    submitted.raise_for_status()
    diagnosis = wait_for(
        client, submitted.json()["links"]["self"],
        {"COMPLETED", "WAITING_REVIEW", "FAILED", "APPROVED_REPORT", "REJECTED"},
        args.timeout,
    )
    if diagnosis["status"] == "FAILED" or not diagnosis.get("report_id"):
        raise RuntimeError(diagnosis)
    report = client.get(f"/api/v1/reports/{diagnosis['report_id']}")
    report.raise_for_status()
    report_value = report.json()
    if any(action.get("execution_allowed") for action in report_value.get("actions", [])):
        raise RuntimeError("An action was marked executable")

    unauthorized_status = None
    approval_status = None
    pending = client.get("/api/v1/approvals", params={"status": "PENDING"})
    pending.raise_for_status()
    matching = [item for item in pending.json()["items"]
                if item["diagnosis_id"] == diagnosis["diagnosis_id"]]
    if matching:
        approval = matching[0]
        decision = {"decision": "approve", "report_hash": approval["report_hash"],
                    "revision": approval["revision"], "reason": "W10隔离验收：仅确认报告已复核，不执行任何动作。"}
        denied = client.post(
            f"/api/v1/approvals/{approval['approval_id']}/decision",
            json=decision,
            headers={"Idempotency-Key": f"w10-unauthorized-{args.id_suffix}"},
        )
        unauthorized_status = denied.status_code
        if unauthorized_status != 401:
            raise RuntimeError(f"Unauthenticated approval returned {unauthorized_status}")
        if args.reviewer_token_file:
            token = Path(args.reviewer_token_file).read_text(encoding="utf-8").strip()
            approved = client.post(
                f"/api/v1/approvals/{approval['approval_id']}/decision",
                json=decision,
                headers={"Authorization": f"Bearer {token}",
                         "Idempotency-Key": f"w10-authorized-{args.id_suffix}"},
            )
            approved.raise_for_status()
            approval_status = approved.json()["status"]

    tools = client.get(f"/api/v1/diagnoses/{diagnosis['diagnosis_id']}/tool-calls")
    tools.raise_for_status()
    result = {
        "schema_version": 1,
        "task_status": task["status"],
        "event_count": len(events.json()["items"]),
        "diagnosis_id_hash": hashlib.sha256(
            diagnosis["diagnosis_id"].encode("utf-8")).hexdigest(),
        "diagnosis_status": diagnosis["status"],
        "report_status": report_value.get("diagnosis_status"),
        "tool_calls": len(tools.json()["items"]),
        "unauthorized_approval_status": unauthorized_status,
        "authorized_approval_status": approval_status,
        "execution_allowed": False,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
