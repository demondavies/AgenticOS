"""Persistent SQLite Task store for AgenticOS.

This capability owns Task persistence. It has no knowledge of Agents, Models,
Policy, or Tools — it only stores and retrieves the Task domain model defined
in core/tasks.py.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from core.tasks import Task

DEFAULT_DB_PATH = r"G:\AgenticOS\data\tasks.db"

_JSON_COLUMNS = ("inputs", "result", "metadata")

_TERMINAL_STATUSES = ("completed", "failed", "cancelled", "rejected")

_COLUMNS = (
    "id",
    "title",
    "description",
    "status",
    "priority",
    "creator",
    "assigned_agent",
    "workspace",
    "parent_task_id",
    "inputs",
    "result",
    "attempt_count",
    "max_retries",
    "created_at",
    "started_at",
    "completed_at",
    "error",
    "metadata",
)


class TaskStore:
    """SQLite-backed persistent Task store."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH) -> None:
        self.db_path = db_path

    def _ensure_schema(self) -> None:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    description TEXT,
                    status TEXT,
                    priority TEXT,
                    creator TEXT,
                    assigned_agent TEXT,
                    workspace TEXT,
                    parent_task_id TEXT,
                    inputs TEXT,
                    result TEXT,
                    attempt_count INTEGER,
                    max_retries INTEGER,
                    created_at TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    error TEXT,
                    metadata TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            conn.commit()

    def init_db(self) -> None:
        self._ensure_schema()

        print(
            f"🗂️ [AgenticOS Tasks] SQLite Core Online. "
            f"Database: {self.db_path}"
        )

    def save_task(self, task: Task) -> None:
        self._ensure_schema()

        data = task.to_dict()

        row = dict(data)
        for column in _JSON_COLUMNS:
            row[column] = json.dumps(row.get(column))

        columns = _COLUMNS
        placeholders = ", ".join("?" for _ in columns)
        update_clause = ", ".join(
            f"{column}=excluded.{column}"
            for column in columns
            if column != "id"
        )

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"""INSERT INTO tasks ({", ".join(columns)})
                    VALUES ({placeholders})
                    ON CONFLICT(id) DO UPDATE SET
                    {update_clause},
                    updated_at=CURRENT_TIMESTAMP""",
                tuple(row.get(column) for column in columns),
            )
            conn.commit()

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        self._ensure_schema()

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM tasks WHERE id = ?",
                (task_id,),
            )
            row = cursor.fetchone()

        if row is None:
            return None

        return self._row_to_dict(row)

    def list_tasks(
        self,
        status: Optional[str] = None,
        workspace: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        self._ensure_schema()

        clauses = []
        params: List[Any] = []

        if status is not None:
            clauses.append("status = ?")
            params.append(status)

        if workspace is not None:
            clauses.append("workspace = ?")
            params.append(workspace)

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                f"""SELECT * FROM tasks {where}
                    ORDER BY created_at DESC LIMIT ?""",
                tuple(params),
            )
            rows = cursor.fetchall()

        return [self._row_to_dict(row) for row in rows]

    def delete_terminal_tasks_older_than(self, days: int = 30) -> int:
        """Delete completed/failed/cancelled/rejected Tasks older than `days`."""
        self._ensure_schema()

        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat()
        placeholders = ", ".join("?" for _ in _TERMINAL_STATUSES)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                f"""DELETE FROM tasks
                    WHERE status IN ({placeholders})
                    AND completed_at IS NOT NULL
                    AND completed_at < ?""",
                (*_TERMINAL_STATUSES, cutoff),
            )
            conn.commit()

        return cursor.rowcount

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        data = dict(row)

        for column in _JSON_COLUMNS:
            value = data.get(column)
            data[column] = json.loads(value) if value is not None else None

        return data
