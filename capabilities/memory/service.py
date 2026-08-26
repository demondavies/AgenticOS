"""Persistent SQLite conversation memory for AgenticOS.

This capability owns message persistence, recent-history retrieval, and
LLM-assisted channel compaction. It has no Discord dependency.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Awaitable, Callable
from typing import Any

DEFAULT_DB_PATH = r"G:\AgenticOS\data\memory.db"
DEFAULT_VAULT_DIR = r"G:\Master_Brain\Master_Brain"

_summarizer: Callable[..., Awaitable[str]] | None = None


def configure_memory_summarizer(
    summarizer: Callable[..., Awaitable[str]] | None,
) -> None:
    """Register the model callback used only when memory compaction is needed."""
    global _summarizer
    _summarizer = summarizer


class MemoryStore:
    """SQLite-backed persistent conversation memory."""

    def __init__(
        self,
        db_path: str = DEFAULT_DB_PATH,
        vault_dir: str = DEFAULT_VAULT_DIR,
    ) -> None:
        self.db_path = db_path
        self.vault_dir = vault_dir

    def init_db(self) -> None:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        os.makedirs(self.vault_dir, exist_ok=True)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_id TEXT,
                    user_id TEXT,
                    role TEXT,
                    content TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            cursor.execute(
                """CREATE TABLE IF NOT EXISTS channel_summaries (
                    channel_id TEXT PRIMARY KEY,
                    summary TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )"""
            )
            conn.commit()

        print(
            f"💾 [AgenticOS Memory] SQLite Core Online. "
            f"Database: {self.db_path}"
        )

    def save_message(
        self,
        channel_id: str,
        user_id: str,
        role: str,
        content: str,
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO messages "
                "(channel_id, user_id, role, content) VALUES (?, ?, ?, ?)",
                (str(channel_id), str(user_id), role, content),
            )
            conn.commit()

    def get_recent_history(
        self,
        channel_id: str,
        limit: int = 20,
    ) -> list[dict[str, str]]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT summary FROM channel_summaries "
                "WHERE channel_id = ?",
                (str(channel_id),),
            )
            summary_row = cursor.fetchone()

            cursor.execute(
                "SELECT role, content FROM messages "
                "WHERE channel_id = ? ORDER BY id DESC LIMIT ?",
                (str(channel_id), limit),
            )
            rows = cursor.fetchall()

        history: list[dict[str, str]] = []

        if summary_row and summary_row[0]:
            history.append(
                {
                    "role": "system",
                    "content": (
                        "[COMPACTED CHANNEL MEMORY SUMMARY]:\n"
                        f"{summary_row[0]}"
                    ),
                }
            )

        for role, content in reversed(rows):
            history.append(
                {
                    "role": str(role),
                    "content": str(content),
                }
            )

        return history

    async def compact_channel_memory(
        self,
        channel_id: str,
        keep_recent: int = 10,
    ) -> str:
        if _summarizer is None:
            raise RuntimeError(
                "Memory summarizer is not configured. "
                "Call configure_memory_summarizer(...) first."
            )

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            cursor.execute(
                "SELECT id, role, content FROM messages "
                "WHERE channel_id = ? ORDER BY id ASC",
                (str(channel_id),),
            )
            all_msgs = cursor.fetchall()

            if len(all_msgs) <= 30:
                return (
                    "Memory log optimal. "
                    "No compaction required (Under 30 entries)."
                )

            print(
                f"🧹 [Memory Compactor] Compacting memory for channel: "
                f"{channel_id} ({len(all_msgs)} msgs)"
            )

            msgs_to_summarize = all_msgs[:-keep_recent]
            ids_to_delete = [m[0] for m in msgs_to_summarize]
            log_text = "\n".join(
                f"{m[1].upper()}: {m[2]}" for m in msgs_to_summarize
            )

            cursor.execute(
                "SELECT summary FROM channel_summaries "
                "WHERE channel_id = ?",
                (str(channel_id),),
            )
            existing_summary = cursor.fetchone()
            prior_context = (
                existing_summary[0] if existing_summary else "None"
            )

        prompt = (
            "You are a database memory compactor agent.\n"
            f"PRIOR SUMMARY:\n{prior_context}\n\n"
            f"NEW CONVERSATION LOGS TO MERGE:\n{log_text}\n\n"
            "Task: Synthesize a concise markdown summary retaining key "
            "facts, user preferences, code context, and ongoing goals. "
            "Output ONLY the bulleted summary without conversational text."
        )

        new_summary = await _summarizer(
            [{"role": "user", "content": prompt}],
            model="hermes3:8b",
            capability="summarization",
        )
        new_summary = str(new_summary).strip()

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO channel_summaries
                   (channel_id, summary, updated_at)
                   VALUES (?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(channel_id) DO UPDATE SET
                   summary=excluded.summary,
                   updated_at=CURRENT_TIMESTAMP""",
                (str(channel_id), new_summary),
            )
            cursor.executemany(
                "DELETE FROM messages WHERE id = ?",
                [(message_id,) for message_id in ids_to_delete],
            )
            conn.commit()

        msg = (
            f"Compaction complete! Merged {len(ids_to_delete)} messages "
            f"into memory core for channel {channel_id}."
        )
        print(f"✅ [Memory Compactor] {msg}")
        return msg


# Default process-local store. The DB remains persistent on disk.
_store = MemoryStore()


def init_db() -> None:
    _store.init_db()


def save_message(
    channel_id: str,
    user_id: str,
    role: str,
    content: str,
) -> None:
    _store.save_message(channel_id, user_id, role, content)


def get_recent_history(
    channel_id: str,
    limit: int = 20,
) -> list[dict[str, str]]:
    return _store.get_recent_history(channel_id, limit)


async def compact_channel_memory(
    channel_id: str,
    keep_recent: int = 10,
) -> str:
    return await _store.compact_channel_memory(channel_id, keep_recent)
