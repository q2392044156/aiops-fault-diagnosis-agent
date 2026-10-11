from io import BytesIO
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from aiops_diag.data.common import digest
from aiops_diag.service.api import ServiceError, create_app
from aiops_diag.service.db import Database, IdempotencyConflict
from aiops_diag.service.pipeline import _event_groups, process
from aiops_diag.service.runtime import ServiceRuntime
from aiops_diag.service import release as release_module


LINE_1 = b"081109 203518 143 INFO dfs.DataNode$DataXceiver: Receiving block blk_-1 src: /10.0.0.1:1\n"
LINE_2 = b"081109 203519 144 ERROR dfs.DataNode$DataXceiver: Failed block blk_-1 at /10.0.0.1:1\n"
NO_BLOCK = b"081109 203520 145 INFO dfs.DataNode: heartbeat ok\n"


class FakeModel:
    manifest = {"release_id": "test_release"}
    threshold = 1.0

    def template(self, row):
        return 2 if row.get("level") == "ERROR" else 1

    def score(self, sequences):
        scores = np.asarray([2.0 if 2 in row else -2.0 for row in sequences])
        return scores, (scores >= self.threshold).astype(np.int8)

    def assert_unchanged(self):
        return None

    def public(self):
        return {"schema_version": 1, "release_id": "test_release",
                "model_id": "logistic_regression", "model_family": "tfidf_lr",
                "threshold": 1.0,
                "anomaly_score_semantics": "larger_is_more_anomalous_uncalibrated",
                "protocol_hash": "protocol", "template_manifest_hash": "templates"}


def config(tmp_path, max_bytes=1024):
    runtime = tmp_path / "runtime"
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    (release_dir / "service_release.json").write_text("{}", encoding="utf-8")
    return {
        "paths": {"runtime_dir": str(runtime), "database": str(runtime / "service.sqlite3")},
        "release_dir": str(release_dir), "processing_hash": "processing",
        "upload": {"max_bytes": max_bytes, "chunk_bytes": 4},
        "processing": {"max_line_bytes": 1024, "parquet_batch_rows": 2,
                       "inference_batch_sessions": 2, "event_max_gap_seconds": 300,
                       "event_max_span_seconds": 1800},
        "worker": {"poll_seconds": 0.01}, "registered_batches": {},
    }


def runtime(tmp_path, max_bytes=1024):
    value = ServiceRuntime(config(tmp_path, max_bytes), load_model=False)
    value.model = FakeModel()
    value.ready_error = None
    return value


class DummyUpload:
    def __init__(self, data, content_type="text/plain"):
        self.file = BytesIO(data)
        self.filename = "sample.log"
        self.content_type = content_type

    async def read(self, size):
        return self.file.read(size)


def upload(data, content_type="text/plain"):
    return DummyUpload(data, content_type)


def drive(coroutine):
    try:
        coroutine.send(None)
    except StopIteration as stopped:
        return stopped.value
    raise AssertionError("Test coroutine unexpectedly required an external event loop")


def test_database_idempotency_and_recovery(tmp_path):
    db = Database(tmp_path / "service.sqlite3")
    db.init()
    row, duplicate = db.create_task("b1", "t1", "upload", "x", "h1", "r", "p",
                                    "f1", "same")
    assert not duplicate and row["status"] == "QUEUED"
    row, duplicate = db.create_task("b1", "t1", "upload", "x", "h1", "r", "p",
                                    "f1", "same")
    assert duplicate and row["task_id"] == "t1"
    with pytest.raises(IdempotencyConflict):
        db.create_task("b2", "t2", "upload", "y", "h2", "r", "p", "f2", "same")
    assert db.claim()["status"] == "RUNNING"
    assert db.recover() == 1
    assert db.one("SELECT status FROM tasks WHERE task_id='t1'")["status"] == "QUEUED"


def test_four_concurrent_submissions_create_one_task(tmp_path):
    service = runtime(tmp_path)

    def submit(_):
        return drive(service.submit_upload(upload(b"same-content")))[0]["task_id"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        task_ids = list(pool.map(submit, range(4)))
    assert len(set(task_ids)) == 1
    assert service.db.one("SELECT COUNT(*) AS n FROM tasks")["n"] == 1


def test_upload_validation_and_content_deduplication(tmp_path):
    service = runtime(tmp_path, max_bytes=8)
    with pytest.raises(EOFError):
        drive(service.submit_upload(upload(b"")))
    with pytest.raises(TypeError):
        drive(service.submit_upload(upload(b"PK\x03\x04x")))
    with pytest.raises(OverflowError):
        drive(service.submit_upload(upload(b"123456789")))
    boundary, _ = drive(service.submit_upload(upload(b"12345678")))
    assert boundary["status"] == "QUEUED"
    first, duplicate = drive(service.submit_upload(upload(b"1234"), "key"))
    second, duplicate2 = drive(service.submit_upload(upload(b"1234"), "key"))
    assert not duplicate and duplicate2 and first["task_id"] == second["task_id"]


def test_idempotency_key_conflict_for_different_uploads(tmp_path):
    service = runtime(tmp_path)
    drive(service.submit_upload(upload(b"one"), "same"))
    with pytest.raises(IdempotencyConflict):
        drive(service.submit_upload(upload(b"two"), "same"))


def test_event_groups_obey_gap_span_and_missing_host():
    base = {"prediction": 1, "host_alias": "host", "threshold": 1.0,
            "anomaly_score": 2.0, "end_time": "2020-01-01T00:00:01"}
    rows = [
        {**base, "session_id": "a", "start_time": "2020-01-01T00:00:00"},
        {**base, "session_id": "b", "start_time": "2020-01-01T00:04:00"},
        {**base, "session_id": "c", "start_time": "2020-01-01T00:10:00"},
        {**base, "session_id": "d", "host_alias": None,
         "start_time": "2020-01-01T00:00:30"},
    ]
    groups = _event_groups(rows, 300, 1800)
    assert sorted(sorted(row["session_id"] for row in group) for group in groups) == [
        ["a", "b"], ["c"], ["d"]]


def test_pipeline_writes_traceable_artifacts(tmp_path):
    cfg = config(tmp_path)
    source = tmp_path / "input.log"
    source.write_bytes(LINE_1 + LINE_2 + NO_BLOCK + b"broken\n")
    source_hash = digest(source)
    task = {"task_id": "tsk_test", "batch_id": "bat_test", "source_kind": "upload",
            "source_ref": str(source), "input_hash": source_hash}
    stages = []
    directory, manifest = process(task, cfg, FakeModel(), stages.append)
    assert stages == ["PARSING", "SCORING", "AGGREGATING"]
    assert manifest["counts"] == {"total_lines": 4, "parsed_lines": 2,
                                  "quarantined_lines": 2, "session_count": 1,
                                  "anomaly_count": 1, "event_count": 1}
    predictions = pq.read_table(directory / "predictions.parquet").to_pylist()
    assert predictions[0]["session_id"] == "blk_-1"
    assert predictions[0]["prediction"] == 1
    logs = pq.read_table(directory / "logs.parquet").to_pylist()
    assert "10.0.0.1" not in logs[0]["redacted_message"]
    assert "blk_-1" not in logs[0]["redacted_message"]


def test_pipeline_bounds_long_lines_and_reuses_verified_completion(tmp_path):
    cfg = config(tmp_path)
    cfg["processing"]["max_line_bytes"] = 128
    source = tmp_path / "bounded.log"
    source.write_bytes(b"x" * 200 + b"\n" + LINE_2.rstrip(b"\n"))
    task = {"task_id": "tsk_bounded", "batch_id": "bat_bounded", "source_kind": "upload",
            "source_ref": str(source), "input_hash": digest(source)}
    directory, manifest = process(task, cfg, FakeModel(), lambda _stage: None)
    assert manifest["counts"]["total_lines"] == 2
    assert manifest["counts"]["quarantined_lines"] == 1
    stages = []
    reused, second = process(task, cfg, FakeModel(), stages.append)
    assert reused == directory and second == manifest and stages == []


def test_release_verification_rejects_changed_component(tmp_path, monkeypatch):
    files = {}
    for name in ("drain3_state", "template_vocab", "tfidf", "logistic_regression",
                 "w2_training", "w2_templates", "w4_release", "w4_manifest"):
        path = tmp_path / name
        path.write_text(name, encoding="utf-8")
        files[name] = path
    cfg = {"release_dir": str(tmp_path / "release"), "config_hash": "service",
           "processing_hash": "processing"}
    components = (
        {"release": "v0.2", "default_model": "logistic_regression"}, {},
        {"selected_similarity": 0.5},
        {"run_id": "w2", "protocol_hash": "protocol", "template_manifest_hash": "templates"},
        files, 4.0,
    )
    monkeypatch.setattr(release_module, "_components", lambda _cfg: components)
    release_module.publish(cfg)
    assert release_module.verify(cfg)["release_id"] == "v0.2_lr"
    files["tfidf"].write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="component changed"):
        release_module.verify(cfg)


def test_database_completion_is_atomic(tmp_path):
    service = runtime(tmp_path)
    source = tmp_path / "input.log"
    source.write_bytes(LINE_1 + LINE_2)
    row, _ = drive(service.submit_upload(upload(source.read_bytes())))
    completed = service.run_one()
    assert completed["status"] == "SUCCEEDED"
    batch = service.db.one("SELECT * FROM batches WHERE batch_id=?", (row["batch_id"],))
    assert batch["session_count"] == 1 and batch["event_count"] == 1
    assert service.db.one("SELECT COUNT(*) AS n FROM sessions")["n"] == 1


def test_api_routes_upload_queries_and_redaction(tmp_path):
    service = runtime(tmp_path)
    app = create_app(service.cfg, start_worker=False, runtime=service)
    routes = {route.path: route.endpoint for route in app.routes if hasattr(route, "endpoint")}
    assert routes["/api/v1/health/live"]()["status"] == "live"
    assert routes["/api/v1/health/ready"]()["status"] == "ready"
    ids = drive(routes["/api/v1/batches/uploads"](upload(LINE_1 + LINE_2), None))
    service.run_one()
    task = routes["/api/v1/tasks/{task_id}"](ids["task_id"])
    assert task["status"] == "SUCCEEDED"
    events = routes["/api/v1/events"](ids["batch_id"], 50, None)
    assert len(events["items"]) == 1
    logs = routes["/api/v1/batches/{batch_id}/logs"](
        ids["batch_id"], "blk_-1", None, None, 1, None)
    assert len(logs["items"]) == 1 and logs["next_cursor"] is not None
    assert "10.0.0.1" not in logs["items"][0]["redacted_message"]
    page2 = routes["/api/v1/batches/{batch_id}/logs"](
        ids["batch_id"], "blk_-1", None, None, 50, logs["next_cursor"])
    assert len(page2["items"]) == 1
    with pytest.raises(ServiceError, match="start must be earlier"):
        routes["/api/v1/batches/{batch_id}/logs"](
            ids["batch_id"], None, "2020-01-02T00:00:00", "2020-01-01T00:00:00", 50, None)


def test_api_upload_routes_map_domain_errors(tmp_path):
    service = runtime(tmp_path, max_bytes=4)
    app = create_app(service.cfg, start_worker=False, runtime=service)
    route = next(route.endpoint for route in app.routes
                 if getattr(route, "path", None) == "/api/v1/batches/uploads")
    with pytest.raises(ServiceError) as too_large:
        drive(route(upload(b"12345"), None))
    assert too_large.value.status == 413 and too_large.value.code == "UPLOAD_TOO_LARGE"
    with pytest.raises(ServiceError) as archive:
        drive(route(upload(b"PK\x03\x04", "application/octet-stream"), None))
    assert archive.value.status == 415 and archive.value.code == "UNSUPPORTED_MEDIA"


def test_registered_batch_is_allowlisted(tmp_path):
    service = runtime(tmp_path)
    with pytest.raises(FileNotFoundError):
        service.submit_registered("unknown")
    parquet = tmp_path / "registered.parquet"
    pq.write_table(pa.table({"log_id": ["x"], "raw_line_no": [1], "raw_hash": ["h"],
                             "timestamp_local": [None], "level": [None], "component": [None],
                             "message": [None], "session_ids": [[]],
                             "parse_status": ["format_error"]}), parquet)
    service.cfg["registered_batches"]["demo"] = {"kind": "w1_parquet", "path": str(parquet)}
    row, duplicate = service.submit_registered("demo")
    assert row["status"] == "QUEUED" and not duplicate
