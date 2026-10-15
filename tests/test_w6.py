import json
import sqlite3
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from aiops_diag.service.db import Database, LeaseLost, QueueFull
from aiops_diag.service.ui_client import ApiClient


def create(db, number, capacity=32):
    suffix = str(number)
    return db.create_task("b" + suffix, "t" + suffix, "upload", "source", "h" + suffix,
                          "release", "processing", "fingerprint" + suffix,
                          max_inflight=capacity)


def test_schema_v1_migrates_idempotently(tmp_path):
    path = tmp_path / "service.sqlite3"
    db = Database(path)
    db.init()
    raw = sqlite3.connect(path)
    raw.execute("UPDATE schema_meta SET version=1")
    raw.commit()
    raw.close()
    db.init()
    db.init()
    assert db.one("SELECT version FROM schema_meta")["version"] == 4
    columns = {row["name"] for row in db.all("PRAGMA table_info(tasks)")}
    assert {"lease_owner", "lease_token", "lease_expires_at"} <= columns


def test_queue_capacity_allows_duplicates_but_rejects_new_tasks(tmp_path):
    db = Database(tmp_path / "service.sqlite3")
    db.init()
    first, duplicate = create(db, 1, capacity=1)
    assert not duplicate
    same, duplicate = create(db, 1, capacity=1)
    assert duplicate and same["task_id"] == first["task_id"]
    with pytest.raises(QueueFull):
        create(db, 2, capacity=1)


def test_lease_expiry_recovery_and_fencing(tmp_path):
    db = Database(tmp_path / "service.sqlite3")
    db.init()
    create(db, 1)
    claimed = db.claim("worker-a", lease_seconds=30)
    old_token = claimed["lease_token"]
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    raw = db.connect()
    raw.execute("UPDATE tasks SET lease_expires_at=? WHERE task_id='t1'", (past,))
    raw.close()
    assert db.recover_expired() == 1
    reclaimed = db.claim("worker-b", lease_seconds=30)
    assert reclaimed["lease_token"] != old_token
    with pytest.raises(LeaseLost):
        db.set_stage("t1", "SCORING", old_token)
    db.set_stage("t1", "SCORING", reclaimed["lease_token"])


def test_worker_heartbeat_and_operation_summary(tmp_path):
    db = Database(tmp_path / "service.sqlite3")
    db.init()
    db.heartbeat("worker", "release")
    create(db, 1)
    summary = db.operation_summary("release", heartbeat_age=15)
    assert summary["worker_ready"] is True
    assert summary["queued"] == 1 and summary["running"] == 0


def test_ui_client_uses_only_http_api():
    def handler(request):
        assert request.url.path.startswith("/api/v1/")
        if request.url.path.endswith("health/ready"):
            return httpx.Response(200, json={"schema_version": 1, "status": "ready",
                                             "detail": None})
        if request.url.path.endswith("operations/summary"):
            return httpx.Response(200, json={"release_id": "release", "worker_ready": True})
        if request.url.path.endswith("batches/registered"):
            if request.method == "GET":
                return httpx.Response(200, json={"schema_version": 1, "items": ["w1_dev"]})
            assert json.loads(request.content)["registered_id"] == "w1_dev"
            return httpx.Response(202, json={"task_id": "task", "batch_id": "batch"})
        return httpx.Response(404)

    client = ApiClient("http://api", transport=httpx.MockTransport(handler))
    assert client.health()["status"] == "ready"
    assert client.operations()["worker_ready"] is True
    assert client.registered_options() == ["w1_dev"]
    assert client.registered("w1_dev")["task_id"] == "task"
    client.close()
