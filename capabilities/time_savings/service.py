"""Internal time savings log — tracks hours saved by using Kaido OS agents."""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

LOG_FILE = Path("internal_time_savings.json")

CATEGORIES = [
    "prospect_research",
    "outreach",
    "audit_report",
    "admin",
    "platform_build",
    "other",
]


@dataclass
class TimeSavingEntry:
    id: str
    hours: float
    category: str
    description: str
    logged_at: str
    logged_by: str = "Kane"


def _load() -> list[dict]:
    if not LOG_FILE.exists():
        return []
    with open(LOG_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save(entries: list[dict]) -> None:
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)


def log_entry(
    hours: float,
    description: str,
    category: str = "other",
    logged_by: str = "Kane",
) -> TimeSavingEntry:
    entry = TimeSavingEntry(
        id=f"ts_{uuid4().hex[:10]}",
        hours=round(hours, 2),
        category=category if category in CATEGORIES else "other",
        description=description,
        logged_at=datetime.now(timezone.utc).isoformat(),
        logged_by=logged_by,
    )
    entries = _load()
    entries.append(asdict(entry))
    _save(entries)
    return entry


def list_entries(category: str | None = None) -> list[TimeSavingEntry]:
    entries = [TimeSavingEntry(**e) for e in _load()]
    if category:
        entries = [e for e in entries if e.category == category]
    return entries


def total_hours() -> float:
    return round(sum(e["hours"] for e in _load()), 2)


def summary() -> dict:
    entries = _load()
    total = round(sum(e["hours"] for e in entries), 2)
    by_cat: dict[str, float] = {}
    for e in entries:
        by_cat[e["category"]] = round(by_cat.get(e["category"], 0) + e["hours"], 2)
    return {"total_hours": total, "entry_count": len(entries), "by_category": by_cat}


def remove_entry(
    hours: float,
    description: str,
    category: str = "other",
    logged_by: str = "Kane",
) -> TimeSavingEntry:
    """Log a negative adjustment to reduce the total hours saved."""
    entry = TimeSavingEntry(
        id=f"ts_{uuid4().hex[:10]}",
        hours=-round(abs(hours), 2),
        category=category if category in CATEGORIES else "other",
        description=f"[ADJUSTMENT] {description}",
        logged_at=datetime.now(timezone.utc).isoformat(),
        logged_by=logged_by,
    )
    entries = _load()
    entries.append(asdict(entry))
    _save(entries)
    return entry
