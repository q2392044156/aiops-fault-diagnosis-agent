"""Run one local framework-candidate API flow without exposing log content."""

import argparse
import json
import time
from pathlib import Path

import httpx


TERMINAL_TASKS = {"SUCCEEDED", "FAILED"}
TERMINAL_DIAGNOSES = {"WAITING_REVIEW", "COMPLETED", "APPROVED_REPORT", "FAILED"}


def wait_for(client, path, terminal, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(path)
        response.raise_for_status()
        body = response.json()
        if body["status"] in terminal:
            return body
        time.sleep(1)
    raise TimeoutError(f"Timed out waiting for {path}")


def run(base_url, timeout):
    with httpx.Client(base_url=base_url, timeout=15) as client:
        health = client.get("/api/v1/health/ready")
        health.raise_for_status()
        release = client.get("/api/v1/agent/releases/current")
        release.raise_for_status()

        task_response = client.post(
            "/api/v1/batches/registered", json={"registered_id": "w1_dev"},
            headers={"Idempotency-Key": "framework-flow-smoke-batch-v1"})
        task_response.raise_for_status()
        submitted_task = task_response.json()
        task = wait_for(client, submitted_task["links"]["self"], TERMINAL_TASKS, timeout)
        if task["status"] != "SUCCEEDED":
            raise RuntimeError(f"Batch failed: {task.get('error')}")

        events_response = client.get("/api/v1/events", params={
            "batch_id": task["batch_id"], "limit": 1})
        events_response.raise_for_status()
        events = events_response.json()["items"]
        if not events:
            raise RuntimeError("Processed batch produced no anomaly event")
        event_id = events[0]["event_id"]

        diagnosis_response = client.post(
            "/api/v1/diagnoses", json={"event_id": event_id, "mode": "auto"},
            headers={"Idempotency-Key": "framework-flow-smoke-diagnosis-v1"})
        diagnosis_response.raise_for_status()
        submitted_diagnosis = diagnosis_response.json()
        diagnosis = wait_for(client, submitted_diagnosis["links"]["self"],
                             TERMINAL_DIAGNOSES, timeout)
        tools_response = client.get(submitted_diagnosis["links"]["tools"])
        tools_response.raise_for_status()
        tool_calls = tools_response.json()["items"]

        report = None
        if diagnosis.get("report_id"):
            report_response = client.get(diagnosis["links"]["report"])
            report_response.raise_for_status()
            report = report_response.json()

        return {
            "schema_version": 1,
            "status": "FRAMEWORK_FLOW_SMOKE",
            "health": health.json()["status"],
            "release_id": release.json()["release_id"],
            "agent_version": release.json()["agent_version"],
            "rag_version": release.json()["rag_version"],
            "task": {"task_id": task["task_id"], "batch_id": task["batch_id"],
                     "status": task["status"], "deduplicated": submitted_task["deduplicated"]},
            "diagnosis": {
                "diagnosis_id": diagnosis["diagnosis_id"],
                "status": diagnosis["status"],
                "current_node": diagnosis["current_node"],
                "deduplicated": submitted_diagnosis["deduplicated"],
                "llm_calls": diagnosis["budget"]["llm_calls"],
                "tool_calls": diagnosis["budget"]["tool_calls"],
            },
            "tool_names": [item["tool_name"] for item in tool_calls],
            "report": ({
                "report_id": report["report_id"],
                "diagnosis_status": report["diagnosis_status"],
                "requires_review": report["requires_review"],
                "execution_allowed_count": sum(
                    bool(item["execution_allowed"]) for item in report["checks"]),
                "invalid_citation_count": sum(
                    not set(item["citation_ids"]) <= {
                        evidence["evidence_id"] for evidence in report["evidence"]}
                    for item in report["checks"]),
                "agent_version": report["provenance"]["agent_version"],
            } if report else None),
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:28000")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--output", type=Path)
    options = parser.parse_args()
    result = run(options.base_url, options.timeout)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if options.output:
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
