import hashlib
import os
import re
import threading
from pathlib import Path

from aiops_diag.data.common import digest, key

from .db import Database
from .pipeline import database_payload, process
from .release import FrozenRelease


IDEMPOTENCY = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class ServiceRuntime:
    def __init__(self, cfg, load_model=True):
        self.cfg = cfg
        self.runtime_dir = Path(cfg["paths"]["runtime_dir"])
        self.inputs_dir = self.runtime_dir / "inputs"
        self.inputs_dir.mkdir(parents=True, exist_ok=True)
        self.db = Database(cfg["paths"]["database"])
        self.db.init()
        self.db.recover()
        self.model = None
        self.ready_error = None
        if load_model:
            try:
                self.model = FrozenRelease(cfg)
            except Exception as exc:
                self.ready_error = f"{type(exc).__name__}: {exc}"
        self.stop_event = threading.Event()
        self.thread = None

    @property
    def ready(self):
        return self.model is not None and self.ready_error is None

    def start(self):
        if not self.ready:
            return
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._loop, name="aiops-single-worker", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=10)

    def _loop(self):
        while not self.stop_event.is_set():
            task = self.db.claim()
            if task is None:
                self.stop_event.wait(float(self.cfg["worker"]["poll_seconds"]))
                continue
            try:
                directory, manifest = process(
                    task, self.cfg, self.model,
                    lambda stage: self.db.set_stage(task["task_id"], stage),
                )
                counts, sessions, events, members, artifacts = database_payload(directory, manifest)
                self.db.complete(task["task_id"], directory, counts, sessions, events,
                                 members, artifacts)
            except Exception as exc:
                self.db.fail(task["task_id"], "PROCESSING_FAILED",
                             f"{type(exc).__name__}: {exc}")

    def run_one(self):
        if not self.ready:
            raise RuntimeError(self.ready_error or "Service is not ready")
        task = self.db.claim()
        if task is None:
            return None
        try:
            directory, manifest = process(
                task, self.cfg, self.model,
                lambda stage: self.db.set_stage(task["task_id"], stage),
            )
            counts, sessions, events, members, artifacts = database_payload(directory, manifest)
            self.db.complete(task["task_id"], directory, counts, sessions, events,
                             members, artifacts)
        except Exception as exc:
            self.db.fail(task["task_id"], "PROCESSING_FAILED", f"{type(exc).__name__}: {exc}")
            raise
        return self.db.one("SELECT * FROM tasks WHERE task_id=?", (task["task_id"],))

    def _identity(self, input_hash):
        identity = key([input_hash, self.model.manifest["release_id"],
                        self.cfg["processing_hash"]])
        return "bat_" + identity[:24], "tsk_" + identity[:24], identity

    def _submit(self, source_kind, source_ref, input_hash, idempotency_key):
        if not self.ready:
            raise RuntimeError(self.ready_error or "Service is not ready")
        if idempotency_key and not IDEMPOTENCY.fullmatch(idempotency_key):
            raise ValueError("Idempotency-Key must contain 1-128 safe ASCII characters")
        batch_id, task_id, fingerprint = self._identity(input_hash)
        task, deduplicated = self.db.create_task(
            batch_id, task_id, source_kind, str(source_ref), input_hash,
            self.model.manifest["release_id"], self.cfg["processing_hash"],
            fingerprint, idempotency_key,
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
