import hashlib
import os
import re
import socket
import threading
import uuid
from pathlib import Path

from aiops_diag.data.common import digest, key
from aiops_diag.retrieval.release import FrozenRetriever

from .db import Database, LeaseLost
from .pipeline import database_payload, process
from .release import FrozenRelease, ReleaseMetadata


IDEMPOTENCY = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class ServiceRuntime:
    def __init__(self, cfg, load_model=False, role="api"):
        self.cfg = cfg
        self.role = role
        self.runtime_dir = Path(cfg["paths"]["runtime_dir"])
        self.inputs_dir = self.runtime_dir / "inputs"
        self.inputs_dir.mkdir(parents=True, exist_ok=True)
        self.db = Database(cfg["paths"]["database"])
        self.db.init()
        self.model = None
        self.release = None
        self.retriever = None
        self.ready_error = None
        try:
            if load_model:
                self.model = FrozenRelease(cfg)
                self.release = self.model
            else:
                self.release = ReleaseMetadata(cfg)
            if role == "api" and cfg.get("retrieval"):
                self.retriever = FrozenRetriever(cfg["retrieval"])
        except Exception as exc:
            self.ready_error = f"{type(exc).__name__}: {exc}"
        self.stop_event = threading.Event()
        self.thread = None
        self.worker_id = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"

    @property
    def manifest(self):
        source = self.model or self.release
        return source.manifest if source else None

    @property
    def ready(self):
        if self.ready_error is not None or self.manifest is None:
            return False
        if self.role == "api" and self.cfg.get("retrieval") and self.retriever is None:
            return False
        if self.retriever is not None and hasattr(self.retriever, "verify_integrity"):
            try:
                self.retriever.verify_integrity()
            except Exception:
                return False
        if self.model is not None:
            return True
        max_age = int(self.cfg.get("worker", {}).get("heartbeat_max_age_seconds", 15))
        return self.db.worker_ready(self.manifest["release_id"], max_age) is not None

    @property
    def ready_detail(self):
        if self.ready_error:
            return self.ready_error
        if self.manifest is None:
            return "Release metadata is unavailable"
        if self.role == "api" and self.cfg.get("retrieval") and self.retriever is None:
            return "Knowledge release is unavailable"
        if self.retriever is not None and hasattr(self.retriever, "verify_integrity"):
            try:
                self.retriever.verify_integrity()
            except Exception as exc:
                return f"Knowledge integrity error: {type(exc).__name__}: {exc}"
        if self.model is None and not self.ready:
            return "No healthy model worker heartbeat"
        return None

    def start(self):
        """Compatibility helper for local tests; production uses the worker CLI."""
        if self.model is None or self.ready_error:
            return
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self.run_forever,
                                       name="aiops-single-worker", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=10)

    def _heartbeat(self, status="READY", details=None):
        if self.manifest:
            self.db.heartbeat(self.worker_id, self.manifest["release_id"], status, details)

    def run_forever(self):
        if self.model is None or self.ready_error:
            raise RuntimeError(self.ready_error or "Worker model is unavailable")
        poll = float(self.cfg["worker"].get("poll_seconds", 0.2))
        heartbeat = float(self.cfg["worker"].get("heartbeat_seconds", 5))
        last_heartbeat = 0.0
        import time
        self.db.recover_expired()
        while not self.stop_event.is_set():
            current = time.monotonic()
            if current - last_heartbeat >= heartbeat:
                self._heartbeat()
                self.db.recover_expired()
                last_heartbeat = current
            try:
                completed = self.run_one()
            except LeaseLost:
                completed = False
            except Exception:
                # The task has already been moved to FAILED by run_one; keep the worker alive.
                completed = False
            if completed is None:
                self.stop_event.wait(min(poll, heartbeat))
        self._heartbeat("STOPPED")

    def run_one(self):
        if self.model is None or self.ready_error:
            raise RuntimeError(self.ready_error or "Worker model is unavailable")
        lease_seconds = int(self.cfg.get("worker", {}).get("lease_seconds", 30))
        heartbeat_seconds = float(self.cfg.get("worker", {}).get("heartbeat_seconds", 5))
        self._heartbeat()
        task = self.db.claim(self.worker_id, lease_seconds)
        if task is None:
            return None
        lease_token = task["lease_token"]
        renew_stop = threading.Event()

        def renew_loop():
            while not renew_stop.wait(min(heartbeat_seconds, max(1, lease_seconds / 3))):
                try:
                    self._heartbeat()
                    self.db.renew(task["task_id"], lease_token, lease_seconds)
                except LeaseLost:
                    return

        renewer = threading.Thread(target=renew_loop, name="aiops-task-lease", daemon=True)
        renewer.start()
        try:
            directory, manifest = process(
                task, self.cfg, self.model,
                lambda stage: self.db.set_stage(task["task_id"], stage, lease_token),
            )
            counts, sessions, events, members, artifacts = database_payload(directory, manifest)
            self.db.complete(task["task_id"], directory, counts, sessions, events,
                             members, artifacts, lease_token)
        except LeaseLost:
            raise
        except Exception as exc:
            try:
                self.db.fail(task["task_id"], "PROCESSING_FAILED",
                             f"{type(exc).__name__}: {exc}", lease_token)
            except LeaseLost:
                pass
            raise
        finally:
            renew_stop.set()
            renewer.join(timeout=2)
            self._heartbeat()
        return self.db.one("SELECT * FROM tasks WHERE task_id=?", (task["task_id"],))

    def _identity(self, input_hash):
        if not self.manifest:
            raise RuntimeError(self.ready_detail or "Service is not ready")
        identity = key([input_hash, self.manifest["release_id"],
                        self.cfg["processing_hash"]])
        return "bat_" + identity[:24], "tsk_" + identity[:24], identity

    def _submit(self, source_kind, source_ref, input_hash, idempotency_key):
        if not self.ready:
            raise RuntimeError(self.ready_detail or "Service is not ready")
        if idempotency_key and not IDEMPOTENCY.fullmatch(idempotency_key):
            raise ValueError("Idempotency-Key must contain 1-128 safe ASCII characters")
        batch_id, task_id, fingerprint = self._identity(input_hash)
        capacity = int(self.cfg.get("worker", {}).get("queue_capacity", 32))
        task, deduplicated = self.db.create_task(
            batch_id, task_id, source_kind, str(source_ref), input_hash,
            self.manifest["release_id"], self.cfg["processing_hash"],
            fingerprint, idempotency_key, capacity,
        )
        return task, deduplicated

    def submit_registered(self, registered_id, idempotency_key=None):
        item = self.cfg["registered_batches"].get(registered_id)
        if not item:
            raise FileNotFoundError("Registered batch was not found")
        path = Path(item["path"])
        if item.get("kind") != "w1_parquet" or not path.is_file() or path.suffix != ".parquet":
            raise ValueError("Registered batch is unavailable or has an unsupported type")
        return self._submit("registered", path.resolve(), digest(path), idempotency_key)

    async def submit_upload(self, upload, idempotency_key=None):
        allowed = {"text/plain", "application/octet-stream", "text/x-log", ""}
        content_type = (upload.content_type or "").split(";", 1)[0].lower()
        filename = (getattr(upload, "filename", "") or "").lower()
        if content_type not in allowed or filename.endswith((".zip", ".gz", ".tar")):
            raise TypeError("Only raw text log uploads are accepted")
        partial = self.inputs_dir / ("upload_" + key(os.urandom(16).hex())[:20] + ".partial")
        hasher = hashlib.sha256()
        size = 0
        prefix = b""
        try:
            with partial.open("wb") as handle:
                while True:
                    chunk = await upload.read(self.cfg["upload"]["chunk_bytes"])
                    if not chunk:
                        break
                    if not prefix:
                        prefix = chunk[:4]
                    size += len(chunk)
                    if size > self.cfg["upload"]["max_bytes"]:
                        raise OverflowError("Upload exceeds the configured size limit")
                    hasher.update(chunk)
                    handle.write(chunk)
            if size == 0:
                raise EOFError("Upload is empty")
            if prefix.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
                raise TypeError("ZIP archives are not accepted")
            input_hash = hasher.hexdigest()
            target = self.inputs_dir / f"{input_hash}.log"
            if target.exists():
                partial.unlink(missing_ok=True)
            else:
                try:
                    os.rename(partial, target)
                except OSError:
                    if target.exists():
                        partial.unlink(missing_ok=True)
                    else:
                        raise
            return self._submit("upload", target.resolve(), input_hash, idempotency_key)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
