"""
Phase 24: Lead Research Engine — Prospect data store.

Stores UK accountancy practice lead profiles in prospects.json at the
project root, following the same pattern as capabilities/clients/service.py.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

PROSPECTS_FILE = Path(os.environ.get("PROSPECTS_FILE", "prospects.json"))


@dataclass
class Prospect:
    id: str
    firm_name: str
    website: str
    staff_count: str      # e.g. "3-5", "1-10", "unknown"
    services: str         # e.g. "Tax, Payroll, Bookkeeping"
    software_stack: str   # e.g. "Xero", "Sage", "unknown"
    pain_signals: str     # extracted from reviews / job listings
    priority: str         # high / medium / low
    status: str           # researched / contacted / replied / meeting / closed / rejected
    researched_at: str
    notes: str = ""
    outreach_email: str = ""   # populated by Phase 25
    outreach_dm: str = ""      # populated by Phase 25


def _load() -> list[Prospect]:
    if not PROSPECTS_FILE.exists():
        return []
    with open(PROSPECTS_FILE, "r", encoding="utf-8") as f:
        return [Prospect(**p) for p in json.load(f)]


def _save(prospects: list[Prospect]) -> None:
    with open(PROSPECTS_FILE, "w", encoding="utf-8") as f:
        json.dump([asdict(p) for p in prospects], f, indent=2)


def add_prospect(
    firm_name: str,
    website: str = "",
    staff_count: str = "unknown",
    services: str = "unknown",
    software_stack: str = "unknown",
    pain_signals: str = "",
    priority: str = "medium",
    notes: str = "",
) -> Prospect:
    prospects = _load()
    prospect_id = f"prospect_{int(datetime.now(timezone.utc).timestamp())}"
    prospect = Prospect(
        id=prospect_id,
        firm_name=firm_name,
        website=website,
        staff_count=staff_count,
        services=services,
        software_stack=software_stack,
        pain_signals=pain_signals or "No clear signals found.",
        priority=priority,
        status="researched",
        researched_at=datetime.now(timezone.utc).isoformat(),
        notes=notes,
    )
    prospects.append(prospect)
    _save(prospects)
    return prospect


def list_prospects(status: str | None = None) -> list[Prospect]:
    prospects = _load()
    if status:
        prospects = [p for p in prospects if p.status == status]
    return prospects


def get_prospect(prospect_id: str) -> Prospect | None:
    for p in _load():
        if p.id == prospect_id:
            return p
    return None


def update_prospect_status(
    prospect_id: str,
    status: str,
    notes: str = "",
) -> Prospect | None:
    prospects = _load()
    for p in prospects:
        if p.id == prospect_id:
            p.status = status
            if notes:
                p.notes = notes
            _save(prospects)
            return p
    return None

def save_outreach(
    prospect_id: str,
    outreach_email: str = "",
    outreach_dm: str = "",
) -> Prospect | None:
    """Store generated outreach drafts against a Prospect record (Phase 25)."""
    prospects = _load()
    for p in prospects:
        if p.id == prospect_id:
            if outreach_email:
                p.outreach_email = outreach_email
            if outreach_dm:
                p.outreach_dm = outreach_dm
            _save(prospects)
            return p
    return None
