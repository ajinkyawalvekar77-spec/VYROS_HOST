"""Small local SQLite store for inspectable API execution records."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from typing import Any, Literal

from .config import get_settings
from .engine_adapter import json_safe


RunStatus = Literal["running", "succeeded", "partial_failure", "failed"]


def _connect() -> sqlite3.Connection:
    path = get_settings().run_store_path
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA busy_timeout=15000")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS run_records (
            run_id TEXT PRIMARY KEY,
            owner_uid TEXT,
            operation TEXT NOT NULL,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL,
            input_provenance_json TEXT NOT NULL,
            configuration_json TEXT NOT NULL,
            result_json TEXT,
            error_json TEXT
        )
        """
    )
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(run_records)").fetchall()
    }
    if "owner_uid" not in columns:
        connection.execute("ALTER TABLE run_records ADD COLUMN owner_uid TEXT")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_run_records_owner ON run_records(owner_uid, created_at)"
    )
    return connection


def _json(value: Any) -> str:
    return json.dumps(json_safe(value), ensure_ascii=False, allow_nan=False)


def create_run(
    operation: Literal["forecast", "plan", "backtest"],
    owner_uid: str,
    input_provenance: dict[str, Any],
    configuration: dict[str, Any],
) -> tuple[str, str]:
    run_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    with closing(_connect()) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO run_records (
                    run_id, owner_uid, operation, created_at, status, input_provenance_json,
                    configuration_json
                ) VALUES (?, ?, ?, ?, 'running', ?, ?)
                """,
                (run_id, owner_uid, operation, created_at, _json(input_provenance), _json(configuration)),
            )
    return run_id, created_at


def finish_run(
    run_id: str,
    status: RunStatus,
    *,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    with closing(_connect()) as connection:
        with connection:
            updated = connection.execute(
                """
                UPDATE run_records
                SET status = ?, result_json = ?, error_json = ?
                WHERE run_id = ?
                """,
                (status, _json(result) if result is not None else None,
                 _json(error) if error is not None else None, run_id),
            )
            if updated.rowcount != 1:
                raise LookupError(f"Run record {run_id} was not found during completion.")


def get_run(run_id: str, owner_uid: str) -> dict[str, Any] | None:
    with closing(_connect()) as connection:
        row = connection.execute(
            "SELECT * FROM run_records WHERE run_id = ? AND owner_uid = ?",
            (run_id, owner_uid),
        ).fetchone()
    if row is None:
        return None
    return {
        "run_id": row["run_id"],
        "operation": row["operation"],
        "created_at": row["created_at"],
        "status": row["status"],
        "input_provenance": json.loads(row["input_provenance_json"]),
        "configuration": json.loads(row["configuration_json"]),
        "result": json.loads(row["result_json"]) if row["result_json"] else None,
        "error": json.loads(row["error_json"]) if row["error_json"] else None,
    }
