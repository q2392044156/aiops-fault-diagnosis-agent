"""SQLite LangGraph checkpointer using the service database.

Business state remains authoritative in ``agent_runs``.  This saver records
only the compact graph state passed by ``LangGraphAgentEngine``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Sequence
from datetime import datetime, timezone
from typing import Any

from langgraph.checkpoint.base import (BaseCheckpointSaver, CheckpointTuple,
                                       WRITES_IDX_MAP, get_checkpoint_id,
                                       get_checkpoint_metadata, writes_sort_key)


class DatabaseCheckpointSaver(BaseCheckpointSaver):
    def __init__(self, database, *, serde=None, default_namespace="agent-v12"):
        super().__init__(serde=serde)
        self.database = database
        self.default_namespace = default_namespace

    def _identity(self, config):
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id")
        if not thread_id:
            raise ValueError("LangGraph checkpoint requires thread_id")
        namespace = configurable.get("checkpoint_ns") or self.default_namespace
        return str(thread_id), str(namespace)

    def _tuple(self, row, config=None):
        checkpoint = self.serde.loads_typed((row["checkpoint_type"], row["checkpoint_blob"]))
        metadata = self.serde.loads_typed((row["metadata_type"], row["metadata_blob"]))
        writes = self.database.all(
            "SELECT * FROM langgraph_writes WHERE thread_id=? AND checkpoint_ns=? "
            "AND checkpoint_id=?",
            (row["thread_id"], row["checkpoint_ns"], row["checkpoint_id"]),
        )
        writes.sort(key=lambda item: writes_sort_key(
            item["task_path"], item["task_id"], int(item["write_index"])))
        pending = [(item["task_id"], item["channel"], self.serde.loads_typed(
            (item["value_type"], item["value_blob"]))) for item in writes]
        stored_config = {"configurable": {
            "thread_id": row["thread_id"], "checkpoint_ns": row["checkpoint_ns"],
            "checkpoint_id": row["checkpoint_id"],
        }}
        parent = None
        if row["parent_checkpoint_id"]:
            parent = {"configurable": {
                "thread_id": row["thread_id"], "checkpoint_ns": row["checkpoint_ns"],
                "checkpoint_id": row["parent_checkpoint_id"],
            }}
        return CheckpointTuple(config or stored_config, checkpoint, metadata, parent, pending)

    def get_tuple(self, config):
        thread_id, namespace = self._identity(config)
        checkpoint_id = get_checkpoint_id(config)
        if checkpoint_id:
            row = self.database.one(
                "SELECT * FROM langgraph_checkpoints WHERE thread_id=? AND checkpoint_ns=? "
                "AND checkpoint_id=?", (thread_id, namespace, checkpoint_id))
        else:
            row = self.database.one(
                "SELECT * FROM langgraph_checkpoints WHERE thread_id=? AND checkpoint_ns=? "
                "ORDER BY created_at DESC,checkpoint_id DESC LIMIT 1", (thread_id, namespace))
        return self._tuple(row, config if checkpoint_id else None) if row else None

    def list(self, config, *, filter=None, before=None, limit=None) -> Iterator[CheckpointTuple]:
        params: list[Any] = []
        clauses = []
        if config:
            thread_id, namespace = self._identity(config)
            clauses.extend(("thread_id=?", "checkpoint_ns=?"))
            params.extend((thread_id, namespace))
        if before and (before_id := get_checkpoint_id(before)):
            clauses.append("checkpoint_id<?")
            params.append(before_id)
        query = "SELECT * FROM langgraph_checkpoints"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC,checkpoint_id DESC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(int(limit))
        for row in self.database.all(query, tuple(params)):
            value = self._tuple(row)
            if not filter or all(value.metadata.get(name) == expected
                                 for name, expected in filter.items()):
                yield value

    def put(self, config, checkpoint, metadata, new_versions):
        thread_id, namespace = self._identity(config)
        checkpoint_type, checkpoint_blob = self.serde.dumps_typed(checkpoint)
        metadata_type, metadata_blob = self.serde.dumps_typed(
            get_checkpoint_metadata(config, metadata))
        parent = config.get("configurable", {}).get("checkpoint_id")
        state_hash = hashlib.sha256(checkpoint_blob).hexdigest()
        stamp = checkpoint.get("ts") or datetime.now(timezone.utc).isoformat()
        with self.database.transaction() as db:
            db.execute(
                "INSERT OR REPLACE INTO langgraph_checkpoints(thread_id,checkpoint_ns,"
                "checkpoint_id,parent_checkpoint_id,checkpoint_type,checkpoint_blob,"
                "metadata_type,metadata_blob,state_hash,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (thread_id, namespace, checkpoint["id"], parent, checkpoint_type,
                 checkpoint_blob, metadata_type, metadata_blob, state_hash, stamp),
            )
        return {"configurable": {"thread_id": thread_id, "checkpoint_ns": namespace,
                                 "checkpoint_id": checkpoint["id"]}}

    def put_writes(self, config, writes: Sequence[tuple[str, Any]], task_id: str,
                   task_path: str = "") -> None:
        thread_id, namespace = self._identity(config)
        checkpoint_id = get_checkpoint_id(config)
        if not checkpoint_id:
            raise ValueError("LangGraph writes require checkpoint_id")
        with self.database.transaction() as db:
            for index, (channel, value) in enumerate(writes):
                write_index = WRITES_IDX_MAP.get(channel, index)
                value_type, value_blob = self.serde.dumps_typed(value)
                statement = ("INSERT OR IGNORE" if write_index >= 0 else "INSERT OR REPLACE")
                db.execute(
                    f"{statement} INTO langgraph_writes(thread_id,checkpoint_ns,checkpoint_id,"
                    "task_id,task_path,write_index,channel,value_type,value_blob) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (thread_id, namespace, checkpoint_id, task_id, task_path, write_index,
                     channel, value_type, value_blob),
                )

    def delete_thread(self, thread_id: str) -> None:
        with self.database.transaction() as db:
            db.execute("DELETE FROM langgraph_writes WHERE thread_id=?", (thread_id,))
            db.execute("DELETE FROM langgraph_checkpoints WHERE thread_id=?", (thread_id,))

    def delete_for_runs(self, run_ids: Sequence[str]) -> None:
        for thread_id in run_ids:
            self.delete_thread(thread_id)

    def copy_thread(self, source_thread_id: str, target_thread_id: str) -> None:
        raise NotImplementedError("Checkpoint thread copying is intentionally disabled")

    def prune(self, thread_ids: Sequence[str], *, strategy: str = "keep_latest") -> None:
        if strategy == "delete":
            for thread_id in thread_ids:
                self.delete_thread(thread_id)
            return
        raise NotImplementedError("Checkpoint pruning requires complete parent-chain analysis")
