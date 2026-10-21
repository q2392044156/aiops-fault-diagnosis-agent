"""Run a small service-level v1.2 DeepSeek validation without exposing secrets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fastapi.testclient import TestClient

from aiops_diag.data.v12_import import import_snapshots
from aiops_diag.service.api import create_app
from aiops_diag.service.config import load as load_service
from aiops_diag.service.db import Database
from aiops_diag.service.runtime import ServiceRuntime


def _prepare(cfg: dict, source_root: Path, work_dir: Path) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    cfg["paths"]["runtime_dir"] = str(work_dir.resolve())
    cfg["paths"]["database"] = str((work_dir / "service.sqlite3").resolve())
    db = Database(cfg["paths"]["database"])
    db.init()
    for split in ("development", "calibration", "independent_test"):
        import_snapshots(
            db,
            source_root / "processed/diagnostic_snapshots.jsonl",
            source_root / "processed/evaluation_labels.jsonl",
            split,
            work_dir / "imports",
        )


def _choose_events(db: Database, count: int) -> list[str]:
    rows = db.all(
        "SELECT e.event_id FROM event_trace_evidence e "
        "JOIN external_event_imports i ON i.event_id=e.event_id "
        "WHERE i.split='development' ORDER BY e.event_id LIMIT ?",
        (count,),
    )
    if len(rows) != count:
        raise RuntimeError(f"Only {len(rows)} trace events are available; {count} required")
    return [row["event_id"] for row in rows]


def run(config: Path, source_root: Path, work_dir: Path, count: int) -> dict:
    cfg = load_service(config)
    _prepare(cfg, source_root, work_dir)
    worker = ServiceRuntime(cfg, role="worker")
    api = ServiceRuntime(cfg, role="api")
    if worker.ready_error or api.ready_error:
        worker.stop()
        api.stop()
        raise RuntimeError(worker.ready_error or api.ready_error)
    if not worker.agent.configured:
        worker.stop()
        api.stop()
        raise RuntimeError("DEEPSEEK_API_KEY is not configured in the process environment")
    event_ids = _choose_events(worker.db, count)
    cases = []
    try:
        with TestClient(create_app(cfg, runtime=api)) as client:
            for ordinal, event_id in enumerate(event_ids, 1):
                response = client.post(
                    "/api/v1/diagnoses",
                    json={"event_id": event_id, "mode": "auto"},
                    headers={"Idempotency-Key": f"v12-online-{ordinal:02d}"},
                )
                response.raise_for_status()
                diagnosis_id = response.json()["diagnosis_id"]
                for _ in range(12):
                    claimed = worker.db.claim_agent("v12-online-validator", 30)
                    if claimed is None:
                        break
                    worker._run_agent(claimed, 30, 5)
                    current = worker.db.get_agent_run(diagnosis_id)
                    if current["status"] not in ("QUEUED", "RUNNING"):
                        break
                diagnosis = client.get(f"/api/v1/diagnoses/{diagnosis_id}")
                diagnosis.raise_for_status()
                body = diagnosis.json()
                report = None
                if body.get("report_id"):
                    report_response = client.get(f"/api/v1/reports/{body['report_id']}")
                    report_response.raise_for_status()
                    report = report_response.json()
                tools = client.get(f"/api/v1/diagnoses/{diagnosis_id}/tool-calls")
                tools.raise_for_status()
                cases.append({
                    "case_id": f"online_{ordinal:02d}",
                    "event_id": event_id,
                    "diagnosis_id": diagnosis_id,
                    "status": body["status"],
                    "diagnosis_status": report.get("diagnosis_status") if report else None,
                    "schema_version": report.get("schema_version") if report else None,
                    "requires_review": report.get("requires_review") if report else None,
                    "tool_names": [item["tool_name"] for item in tools.json()["items"]],
                    "tool_calls": body["budget"]["tool_calls"],
                    "llm_calls": body["budget"]["llm_calls"],
                    "tokens": body["budget"]["tokens"],
                    "estimated_cost_cny": body["budget"]["estimated_cost_cny"],
                    "error_code": (body.get("error") or {}).get("code"),
                })
    finally:
        worker.stop()
        # The TestClient lifespan closes the API runtime. Calling stop again is safe.
        api.stop()
    passed = all(
        row["status"] in {"COMPLETED", "WAITING_REVIEW"}
        and row["schema_version"] == 2
        and row["llm_calls"] >= 1
        and row["error_code"] is None
        for row in cases
    )
    return {
        "schema_version": 1,
        "status": "V12_ONLINE_ENGINEERING_VALIDATION",
        "formal_independent_evaluation": False,
        "case_count": len(cases),
        "passed": passed,
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/service_v12_rc1.yaml"))
    parser.add_argument("--source-root", type=Path, default=Path("data/external/loghub"))
    parser.add_argument("--work-dir", type=Path, default=Path("runtime/v12_online_validation"))
    parser.add_argument("--output", type=Path,
                        default=Path("evaluation/v1.2/v12_rc1_validation/online.json"))
    parser.add_argument("--count", type=int, default=3, choices=range(1, 7))
    args = parser.parse_args()
    result = run(args.config, args.source_root, args.work_dir, args.count)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps({"status": result["status"], "case_count": result["case_count"],
                      "passed": result["passed"]}, ensure_ascii=False))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
