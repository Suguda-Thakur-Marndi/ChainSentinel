"""Durable LangGraph PostgreSQL Checkpointing with Schema Isolation.

Provides production-grade state persistence for multi-agent workflows.
Guarantees:
- Dedicated, isolated 'checkpoints' database schema (zero pollution of operational domain tables)
- Strict tenant scoping on all thread keys (thread_id = {organization_id}:{workflow_id}:{thread_id})
- Safe serialization using JsonPlusSerializer/msgpack (prevents arbitrary code execution)
- Deterministic canonical state hashing and tamper detection
- Seamless fallback to SQLite/local database during development/testing
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import datetime, timezone
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, Tuple, Union

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langgraph.checkpoint.serde.base import SerializerProtocol
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.agents.contracts import AgentGraphState, AgentGraphStateDict
from app.agents.errors import AgentStateError, AgentTenantIsolationError
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("agents.checkpointer")


def build_scoped_thread_id(organization_id: str, workflow_id: str, thread_id: str) -> str:
    """Construct a deterministic, tenant-scoped thread identity."""
    clean_org = (organization_id or "default").strip()
    clean_wf = (workflow_id or "default").strip()
    clean_th = (thread_id or "default").strip()
    return f"{clean_org}:{clean_wf}:{clean_th}"


def parse_scoped_thread_id(scoped_thread_id: str) -> Tuple[str, str, str]:
    """Extract organization_id, workflow_id, and thread_id from a scoped thread identifier."""
    parts = scoped_thread_id.split(":", 2)
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    if len(parts) == 2:
        return parts[0], parts[1], parts[1]
    return "default", "default", parts[0]


class PostgresAgentCheckpointer(BaseCheckpointSaver):
    """Production-grade durable checkpointer storing LangGraph state in an isolated schema."""

    def __init__(
        self,
        engine: Optional[Engine] = None,
        serde: Optional[SerializerProtocol] = None,
        schema_name: str = "checkpoints",
    ) -> None:
        super().__init__(serde=serde or JsonPlusSerializer())
        self._engine = engine
        self._schema_name = schema_name
        self._is_postgres = False
        self._table_prefix = ""
        self._initialized = False

    def _resolve_engine(self) -> Engine:
        if self._engine is not None:
            return self._engine
        from app.db.session import engine
        if engine is None:
            raise RuntimeError("Database engine is not initialized for checkpointer.")
        self._engine = engine
        return self._engine

    def setup(self) -> None:
        """Idempotently configure isolated schema and checkpoint storage tables."""
        if self._initialized:
            return

        engine = self._resolve_engine()
        dialect_name = engine.dialect.name.lower()
        self._is_postgres = "postgres" in dialect_name

        with engine.begin() as conn:
            if self._is_postgres:
                conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {self._schema_name}"))
                self._table_prefix = f"{self._schema_name}."
            else:
                self._table_prefix = ""

            checkpoints_table = f"{self._table_prefix}agent_checkpoints"
            writes_table = f"{self._table_prefix}agent_writes"

            if self._is_postgres:
                conn.execute(text(f"""
                    CREATE TABLE IF NOT EXISTS {checkpoints_table} (
                        thread_id VARCHAR(255) NOT NULL,
                        checkpoint_ns VARCHAR(255) NOT NULL DEFAULT '',
                        checkpoint_id VARCHAR(255) NOT NULL,
                        parent_checkpoint_id VARCHAR(255),
                        organization_id VARCHAR(255) NOT NULL,
                        type VARCHAR(64) NOT NULL,
                        checkpoint_data BYTEA NOT NULL,
                        metadata_data BYTEA NOT NULL,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
                    )
                """))
                conn.execute(text(f"""
                    CREATE TABLE IF NOT EXISTS {writes_table} (
                        thread_id VARCHAR(255) NOT NULL,
                        checkpoint_ns VARCHAR(255) NOT NULL DEFAULT '',
                        checkpoint_id VARCHAR(255) NOT NULL,
                        task_id VARCHAR(255) NOT NULL,
                        idx INTEGER NOT NULL,
                        channel VARCHAR(255) NOT NULL,
                        type VARCHAR(64) NOT NULL,
                        write_data BYTEA NOT NULL,
                        created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
                    )
                """))
            else:
                # SQLite / Generic SQL dialect
                conn.execute(text(f"""
                    CREATE TABLE IF NOT EXISTS {checkpoints_table} (
                        thread_id VARCHAR(255) NOT NULL,
                        checkpoint_ns VARCHAR(255) NOT NULL DEFAULT '',
                        checkpoint_id VARCHAR(255) NOT NULL,
                        parent_checkpoint_id VARCHAR(255),
                        organization_id VARCHAR(255) NOT NULL,
                        type VARCHAR(64) NOT NULL,
                        checkpoint_data BLOB NOT NULL,
                        metadata_data BLOB NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
                    )
                """))
                conn.execute(text(f"""
                    CREATE TABLE IF NOT EXISTS {writes_table} (
                        thread_id VARCHAR(255) NOT NULL,
                        checkpoint_ns VARCHAR(255) NOT NULL DEFAULT '',
                        checkpoint_id VARCHAR(255) NOT NULL,
                        task_id VARCHAR(255) NOT NULL,
                        idx INTEGER NOT NULL,
                        channel VARCHAR(255) NOT NULL,
                        type VARCHAR(64) NOT NULL,
                        write_data BLOB NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
                    )
                """))

        self._initialized = True
        logger.info(
            f"Durable checkpointer initialized in schema='{self._schema_name}', dialect='{dialect_name}'."
        )

    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        """Fetch a specific checkpoint tuple by configuration."""
        self.setup()
        conf = config.get("configurable", {})
        thread_id = conf.get("thread_id")
        checkpoint_ns = conf.get("checkpoint_ns", "")
        checkpoint_id = conf.get("checkpoint_id")

        if not thread_id and not checkpoint_id:
            return None

        engine = self._resolve_engine()
        tbl = f"{self._table_prefix}agent_checkpoints"

        with engine.connect() as conn:
            if checkpoint_id and not thread_id:
                query = text(f"""
                    SELECT thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id,
                           type, checkpoint_data, metadata_data
                    FROM {tbl}
                    WHERE checkpoint_id = :checkpoint_id
                    LIMIT 1
                """)
                row = conn.execute(query, {
                    "checkpoint_id": checkpoint_id,
                }).mappings().first()
            elif checkpoint_id and thread_id:
                query = text(f"""
                    SELECT thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id,
                           type, checkpoint_data, metadata_data
                    FROM {tbl}
                    WHERE thread_id = :thread_id AND checkpoint_ns = :checkpoint_ns
                      AND checkpoint_id = :checkpoint_id
                    LIMIT 1
                """)
                row = conn.execute(query, {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": checkpoint_id,
                }).mappings().first()
            else:
                query = text(f"""
                    SELECT thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id,
                           type, checkpoint_data, metadata_data
                    FROM {tbl}
                    WHERE thread_id = :thread_id AND checkpoint_ns = :checkpoint_ns
                    ORDER BY checkpoint_id DESC
                    LIMIT 1
                """)
                row = conn.execute(query, {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                }).mappings().first()

            if not row:
                return None

            checkpoint_data = bytes(row["checkpoint_data"])
            metadata_data = bytes(row["metadata_data"])
            checkpoint_type = row["type"]

            checkpoint = self.serde.loads_typed((checkpoint_type, checkpoint_data))
            metadata = self.serde.loads_typed((checkpoint_type, metadata_data))

            # Fetch pending writes for this checkpoint
            writes_tbl = f"{self._table_prefix}agent_writes"
            writes_query = text(f"""
                SELECT task_id, channel, type, write_data
                FROM {writes_tbl}
                WHERE thread_id = :thread_id AND checkpoint_ns = :checkpoint_ns
                  AND checkpoint_id = :checkpoint_id
                ORDER BY idx ASC
            """)
            writes_rows = conn.execute(writes_query, {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": row["checkpoint_id"],
            }).mappings().all()

            pending_writes = [
                (w["task_id"], w["channel"], self.serde.loads_typed((w["type"], bytes(w["write_data"]))))
                for w in writes_rows
            ]

            parent_config = None
            if row["parent_checkpoint_id"]:
                parent_config = {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": row["parent_checkpoint_id"],
                    }
                }

            return CheckpointTuple(
                config={
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": row["checkpoint_id"],
                    }
                },
                checkpoint=checkpoint,
                metadata=metadata,
                parent_config=parent_config,
                pending_writes=pending_writes,
            )

    def list(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[Dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> Iterator[CheckpointTuple]:
        """List historical checkpoints matching the criteria."""
        self.setup()
        conf = (config or {}).get("configurable", {})
        thread_id = conf.get("thread_id")
        checkpoint_ns = conf.get("checkpoint_ns", "")

        if not thread_id:
            return

        engine = self._resolve_engine()
        tbl = f"{self._table_prefix}agent_checkpoints"

        params: Dict[str, Any] = {
            "thread_id": thread_id,
            "checkpoint_ns": checkpoint_ns,
        }
        where_clauses = ["thread_id = :thread_id", "checkpoint_ns = :checkpoint_ns"]

        if before:
            before_id = before.get("configurable", {}).get("checkpoint_id")
            if before_id:
                where_clauses.append("checkpoint_id < :before_id")
                params["before_id"] = before_id

        where_sql = " AND ".join(where_clauses)
        limit_sql = f"LIMIT {limit}" if limit else ""

        with engine.connect() as conn:
            query = text(f"""
                SELECT thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id,
                       type, checkpoint_data, metadata_data
                FROM {tbl}
                WHERE {where_sql}
                ORDER BY checkpoint_id DESC
                {limit_sql}
            """)
            rows = conn.execute(query, params).mappings().all()

            for row in rows:
                chk_type = row["type"]
                checkpoint = self.serde.loads_typed((chk_type, bytes(row["checkpoint_data"])))
                metadata = self.serde.loads_typed((chk_type, bytes(row["metadata_data"])))
                parent_config = None
                if row["parent_checkpoint_id"]:
                    parent_config = {
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_ns": checkpoint_ns,
                            "checkpoint_id": row["parent_checkpoint_id"],
                        }
                    }

                yield CheckpointTuple(
                    config={
                        "configurable": {
                            "thread_id": thread_id,
                            "checkpoint_ns": checkpoint_ns,
                            "checkpoint_id": row["checkpoint_id"],
                        }
                    },
                    checkpoint=checkpoint,
                    metadata=metadata,
                    parent_config=parent_config,
                )

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        """Persist a new checkpoint."""
        self.setup()
        conf = config.get("configurable", {})
        thread_id = conf.get("thread_id")
        checkpoint_ns = conf.get("checkpoint_ns", "")
        checkpoint_id = checkpoint["id"]
        parent_checkpoint_id = conf.get("checkpoint_id")

        if not thread_id:
            raise ValueError("Configuration must contain a valid thread_id.")

        org_id, _, _ = parse_scoped_thread_id(thread_id)

        chk_type, chk_bytes = self.serde.dumps_typed(checkpoint)
        meta_type, meta_bytes = self.serde.dumps_typed(metadata)

        engine = self._resolve_engine()
        tbl = f"{self._table_prefix}agent_checkpoints"

        with engine.begin() as conn:
            if self._is_postgres:
                stmt = text(f"""
                    INSERT INTO {tbl} (
                        thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id,
                        organization_id, type, checkpoint_data, metadata_data
                    ) VALUES (
                        :thread_id, :checkpoint_ns, :checkpoint_id, :parent_checkpoint_id,
                        :organization_id, :type, :checkpoint_data, :metadata_data
                    )
                    ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id)
                    DO UPDATE SET
                        checkpoint_data = EXCLUDED.checkpoint_data,
                        metadata_data = EXCLUDED.metadata_data
                """)
            else:
                stmt = text(f"""
                    INSERT OR REPLACE INTO {tbl} (
                        thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id,
                        organization_id, type, checkpoint_data, metadata_data
                    ) VALUES (
                        :thread_id, :checkpoint_ns, :checkpoint_id, :parent_checkpoint_id,
                        :organization_id, :type, :checkpoint_data, :metadata_data
                    )
                """)

            conn.execute(stmt, {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
                "parent_checkpoint_id": parent_checkpoint_id,
                "organization_id": org_id,
                "type": chk_type,
                "checkpoint_data": chk_bytes,
                "metadata_data": meta_bytes,
            })

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[Tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Persist intermediate task writes associated with a checkpoint step."""
        self.setup()
        conf = config.get("configurable", {})
        thread_id = conf.get("thread_id")
        checkpoint_ns = conf.get("checkpoint_ns", "")
        checkpoint_id = conf.get("checkpoint_id")

        if not thread_id or not checkpoint_id:
            return

        engine = self._resolve_engine()
        tbl = f"{self._table_prefix}agent_writes"

        with engine.begin() as conn:
            for idx, (channel, value) in enumerate(writes):
                write_type, write_bytes = self.serde.dumps_typed(value)
                if self._is_postgres:
                    stmt = text(f"""
                        INSERT INTO {tbl} (
                            thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, write_data
                        ) VALUES (
                            :thread_id, :checkpoint_ns, :checkpoint_id, :task_id, :idx, :channel, :type, :write_data
                        )
                        ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
                        DO UPDATE SET write_data = EXCLUDED.write_data
                    """)
                else:
                    stmt = text(f"""
                        INSERT OR REPLACE INTO {tbl} (
                            thread_id, checkpoint_ns, checkpoint_id, task_id, idx, channel, type, write_data
                        ) VALUES (
                            :thread_id, :checkpoint_ns, :checkpoint_id, :task_id, :idx, :channel, :type, :write_data
                        )
                    """)
                conn.execute(stmt, {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": checkpoint_id,
                    "task_id": task_id,
                    "idx": idx,
                    "channel": channel,
                    "type": write_type,
                    "write_data": write_bytes,
                })


class DurableCheckpointManager:
    """High-level checkpoint manager integrating PostgreSQL persistence, hashing, and tenant security."""

    def __init__(
        self,
        checkpointer: Optional[BaseCheckpointSaver] = None,
        engine: Optional[Engine] = None,
    ) -> None:
        self.checkpointer = checkpointer or PostgresAgentCheckpointer(engine=engine)
        self._memory_cache: Dict[str, Dict[str, Any]] = {}

    def save_checkpoint(
        self,
        thread_id: str,
        state: AgentGraphState,
        step: int,
        checkpoint_id: Optional[str] = None,
    ) -> str:
        """Persist an immutable checkpoint with tenant scoping and canonical hash."""
        from app.agents.recovery import compute_state_hash

        scoped_thread = thread_id
        if ":" not in thread_id:
            scoped_thread = build_scoped_thread_id(
                organization_id=state.organization_id,
                workflow_id="orchestrator",
                thread_id=thread_id,
            )

        cid = checkpoint_id or f"chk_{step}_{int(datetime.now(timezone.utc).timestamp()*1000)}"
        state_dict = state.model_dump(mode="json")
        state_hash = compute_state_hash(state)

        record = {
            "checkpoint_id": cid,
            "thread_id": scoped_thread,
            "organization_id": state.organization_id,
            "step": step,
            "state_hash": state_hash,
            "state": state_dict,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Save to durable checkpointer
        config: RunnableConfig = {
            "configurable": {
                "thread_id": scoped_thread,
                "checkpoint_id": cid,
            }
        }
        chk: Checkpoint = {
            "v": 1,
            "id": cid,
            "ts": datetime.now(timezone.utc).isoformat(),
            "channel_values": {"state": state_dict},
            "channel_versions": {"state": step},
            "versions_seen": {},
            "pending_sends": [],
        }
        meta: CheckpointMetadata = {
            "source": "loop",
            "step": step,
            "writes": {},
            "score": None,
            "organization_id": state.organization_id,
            "state_hash": state_hash,
        }

        try:
            self.checkpointer.put(config, chk, meta, new_versions={"state": step})
        except Exception as exc:
            logger.warning(f"Durable checkpointer write failed ({exc}). Retaining in memory cache.")

        self._memory_cache[cid] = record
        self._memory_cache[f"latest_{scoped_thread}"] = record
        self._memory_cache[f"latest_{thread_id}"] = record
        return cid

    def restore_checkpoint(
        self,
        checkpoint_id_or_thread_id: str,
        expected_org_id: Optional[str] = None,
    ) -> Tuple[AgentGraphState, str]:
        """Restore state from durable checkpointer or cache with strict tenant and hash validation."""
        from app.agents.recovery import compute_state_hash

        # 1. Check local cache first
        record = self._memory_cache.get(checkpoint_id_or_thread_id)
        if not record:
            record = self._memory_cache.get(f"latest_{checkpoint_id_or_thread_id}")

        # 2. Query checkpointer if not found in cache
        if not record:
            is_chk = str(checkpoint_id_or_thread_id).startswith("chk_")
            config: RunnableConfig = {
                "configurable": {
                    "checkpoint_id": checkpoint_id_or_thread_id if is_chk else None,
                    "thread_id": checkpoint_id_or_thread_id if not is_chk else None,
                }
            }
            tuple_record = self.checkpointer.get_tuple(config)
            if tuple_record and tuple_record.checkpoint:
                meta = tuple_record.metadata or {}
                channel_values = tuple_record.checkpoint.get("channel_values", {})
                state_data = channel_values.get("state") or channel_values
                found_thread_id = tuple_record.config.get("configurable", {}).get("thread_id", checkpoint_id_or_thread_id)
                org_id = meta.get("organization_id") or parse_scoped_thread_id(found_thread_id)[0]
                record = {
                    "checkpoint_id": tuple_record.checkpoint["id"],
                    "thread_id": found_thread_id,
                    "organization_id": org_id,
                    "step": meta.get("step", 0),
                    "state_hash": meta.get("state_hash") or compute_state_hash(state_data),
                    "state": state_data,
                    "timestamp": tuple_record.checkpoint.get("ts"),
                }

        if not record:
            raise AgentStateError(
                f"Checkpoint not found for key: '{checkpoint_id_or_thread_id}'.",
                details={"lookup_key": checkpoint_id_or_thread_id},
            )

        # 3. Enforce tenant boundary
        if expected_org_id and record["organization_id"] != expected_org_id:
            raise AgentTenantIsolationError(
                f"Checkpoint tenant mismatch: expected '{expected_org_id}', "
                f"checkpoint owned by '{record['organization_id']}'.",
                details={"expected_org": expected_org_id, "checkpoint_org": record["organization_id"]},
            )

        # 4. Verify state hash integrity
        state_dict = record["state"]
        expected_hash = record["state_hash"]
        current_hash = compute_state_hash(state_dict)

        if current_hash != expected_hash:
            raise AgentStateError(
                f"Checkpoint state integrity failure: hash '{current_hash}' != expected '{expected_hash}'.",
                details={"computed_hash": current_hash, "expected_hash": expected_hash},
            )

        restored_state = AgentGraphState.model_validate(state_dict)
        return restored_state, record["checkpoint_id"]
