import argparse
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from aiops_diag.service.api import create_app
from aiops_diag.service.config import load
from aiops_diag.service.runtime import ServiceRuntime


def main():
    parser = argparse.ArgumentParser(description="W9 local approval API smoke test")
    parser.add_argument("--config", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--token-file", required=True)
    args = parser.parse_args()
    os.environ["AIOPS_REVIEWER_REGISTRY_FILE"] = str(Path(args.registry).resolve())
    cfg = load(args.config)
    runtime = ServiceRuntime(cfg, role="api")
    pending = runtime.db.one(
        "SELECT * FROM approvals WHERE status='PENDING' ORDER BY created_at DESC LIMIT 1")
    if not pending:
        raise SystemExit("No pending approval is available for the smoke test")
    token = Path(args.token_file).read_text(encoding="utf-8").strip()
    with TestClient(create_app(cfg, runtime=runtime)) as client:
        common = {"Authorization": "Bearer " + token}
        bad = client.post(
            f"/api/v1/approvals/{pending['approval_id']}/decision",
            json={"decision": "approve", "report_hash": "0" * 64,
                  "revision": pending["revision"], "reason": "version binding test"},
            headers={**common, "Idempotency-Key": "w9-bad-hash"},
        )
        good = client.post(
            f"/api/v1/approvals/{pending['approval_id']}/decision",
            json={"decision": "approve", "report_hash": pending["report_hash"],
                  "revision": pending["revision"], "reason": "reviewed without execution"},
            headers={**common, "Idempotency-Key": "w9-good-approval"},
        )
    final = runtime.db.get_agent_run(pending["diagnosis_id"])
    print(json.dumps({"bad_hash_status": bad.status_code,
                      "approval_status": good.json().get("status"),
                      "diagnosis_status": final["status"],
                      "execution_performed": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
