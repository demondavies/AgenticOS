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
from uuid import uuid4

PROSPECTS_FILE = Path(os.environ.get("PROSPECTS_FILE", "prospects.json"))


@dataclass
class Prospect:
    id: str
    firm_name: str
    website: str = ""
    contact_name: str = ""
    email: str = ""
    linkedin_url: str = ""
    industry: str = ""
    employee_count: str = ""
    # Legacy aliases kept for backward compat
    staff_count: str = ""
    services: str = ""
    tech_stack: str = ""
    software_stack: str = ""
    pain_signals: str = ""
    priority: str = "medium"
    status: str = "researched"
    researched_at: str = ""
    added_at: str = ""
    notes: str = ""
    outreach_email: str = ""
    outreach_dm: str = ""


def _load() -> list[Prospect]:
    if not PROSPECTS_FILE.exists():
        return []
    with open(PROSPECTS_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)
    valid_fields = {f.name for f in __import__("dataclasses").fields(Prospect)}
    return [Prospect(**{k: v for k, v in p.items() if k in valid_fields}) for p in raw]


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
    prospect_id = f"prospect_{int(datetime.now(timezone.utc).timestamp())}_{uuid4().hex[:6]}"
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


def get_prospect_by_name(name: str) -> "Prospect | None":
    """Fuzzy-match a prospect by firm name (case-insensitive substring)."""
    name_lower = name.lower().strip()
    best = None
    for p in _load():
        if p.firm_name.lower() == name_lower:
            return p
        if name_lower in p.firm_name.lower():
            best = p
    return best


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
