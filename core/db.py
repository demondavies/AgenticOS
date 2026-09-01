"""Kaido OS — shared SQLite database (kaido.db).

Single connection factory + schema bootstrap for the prospects store and
the unattended discovery queue. Kept deliberately small: callers open their
own short-lived connection per operation via get_db(), matching the pattern
already used by capabilities/tasks/service.py for tasks.db.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "kaido.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS prospects (
    id TEXT PRIMARY KEY,
    firm_name TEXT,
    website TEXT,
    verdict TEXT,
    status TEXT DEFAULT 'researched',
    confidence INTEGER,
    total_score INTEGER,
    county TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS discovery_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    town TEXT NOT NULL,
    county TEXT NOT NULL,
    region TEXT,
    status TEXT DEFAULT 'pending',
    queued_at TEXT DEFAULT (datetime('now')),
    started_at TEXT,
    completed_at TEXT,
    result_count INTEGER DEFAULT 0,
    UNIQUE(town, county)
);

CREATE INDEX IF NOT EXISTS idx_prospects_verdict ON prospects(verdict);
CREATE INDEX IF NOT EXISTS idx_prospects_status ON prospects(status);
CREATE INDEX IF NOT EXISTS idx_prospects_county ON prospects(county);
CREATE INDEX IF NOT EXISTS idx_queue_status ON discovery_queue(status);

CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    detail TEXT,
    minutes_saved INTEGER NOT NULL DEFAULT 0,
    logged_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_activity_logged_at ON activity_log(logged_at);
"""


def get_db() -> sqlite3.Connection:
    """Open a new connection to kaido.db with WAL mode + row access by name."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def log_activity(action: str, detail: str = "", minutes_saved: int = 0) -> None:
    """Insert one row into activity_log. Fire-and-forget — never raises."""
    try:
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO activity_log (action, detail, minutes_saved) VALUES (?,?,?)",
                (action, detail, minutes_saved),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass  # never block the caller


def get_activity_summary() -> dict:
    """Return total hours saved and breakdown by action."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT action, COUNT(*) as runs, SUM(minutes_saved) as mins "
            "FROM activity_log GROUP BY action"
        ).fetchall()
        total_mins = conn.execute(
            "SELECT COALESCE(SUM(minutes_saved),0) FROM activity_log"
        ).fetchone()[0]
        return {
            "total_minutes": total_mins,
            "total_hours": round(total_mins / 60, 1),
            "breakdown": [dict(r) for r in rows],
        }
    finally:
        conn.close()


def init_db() -> None:
    """Create the kaido.db schema if it does not already exist."""
    conn = get_db()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()
