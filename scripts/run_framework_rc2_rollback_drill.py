"""Verify SQLite backup and the RC2 legacy backend rollback path."""

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from aiops_diag.agent_v11.engine import AgentEngine as LegacyCandidateEngine
from aiops_diag.data.common import digest
from aiops_diag.service.config import load as load_service
from aiops_diag.service.runtime import ServiceRuntime


ROOT = Path(__file__).resolve().parents[1]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "runtime/"
                        "framework_rc2_sealed_once/paired/framework_candidate/"
                        "runtime/service.sqlite3")
    parser.add_argument("--work-dir", type=Path,
                        default=ROOT / "runtime/framework_rc2_rollback_drill")
    parser.add_argument("--output", type=Path, default=ROOT / "deliverables/results/"
                        "framework_rollback_drill_rc2.json")
    options = parser.parse_args()
    if options.work_dir.exists() or options.output.exists():
        raise SystemExit("Use a new work/output path for a rollback drill")
    options.work_dir.mkdir(parents=True)
    target = options.work_dir / "service.sqlite3"
    with sqlite3.connect(options.source) as source, sqlite3.connect(target) as destination:
        source.backup(destination)
        integrity = destination.execute("PRAGMA integrity_check").fetchone()[0]
    before_hashes = [tuple(row) for row in sqlite3.connect(target).execute(
        "SELECT report_id,report_hash,revision FROM incident_reports ORDER BY report_id")]
    cfg = load_service(ROOT / "configs/service_v11_framework_base_rc2.yaml")
    cfg["paths"]["runtime_dir"] = str(options.work_dir)
    cfg["paths"]["database"] = str(target)
    runtime = ServiceRuntime(cfg, role="worker")
    try:
        reports = runtime.db.one("SELECT COUNT(*) AS n FROM incident_reports")["n"]
        approvals = runtime.db.one("SELECT COUNT(*) AS n FROM approvals")["n"]
        pending = runtime.db.one(
            "SELECT COUNT(*) AS n FROM approvals WHERE status='PENDING'")["n"]
        duplicate_approvals = runtime.db.one(
            "SELECT COUNT(*) AS n FROM (SELECT report_id,COUNT(*) c FROM approvals "
            "GROUP BY report_id HAVING c>1)")["n"]
        after_hashes = [tuple(row.values()) for row in runtime.db.all(
            "SELECT report_id,report_hash,revision FROM incident_reports ORDER BY report_id")]
        checks = {
            "sqlite_backup_integrity": integrity == "ok",
            "legacy_backend_loaded": (runtime.ready_error is None
                                      and type(runtime.agent) is LegacyCandidateEngine),
            "existing_reports_readable": reports == 30,
            "report_hashes_and_revisions_unchanged": before_hashes == after_hashes,
            "no_duplicate_approvals": duplicate_approvals == 0,
            "pending_approvals_survive_backend_switch": pending > 0,
        }
        result = {"schema_version": 1, "status": "RC2_LEGACY_ROLLBACK_DRILL",
                  "generated_at": datetime.now(timezone.utc).isoformat(),
                  "source_database_sha256": digest(options.source),
                  "backup_database_sha256": digest(target),
                  "legacy_release_id": runtime.agent_release["release_id"],
                  "report_count": reports, "approval_count": approvals,
                  "pending_approval_count": pending,
                  "database_migration_performed": False,
                  "checks": checks, "passed": all(checks.values())}
    finally:
        runtime.stop()
    options.output.parent.mkdir(parents=True, exist_ok=True)
    options.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
