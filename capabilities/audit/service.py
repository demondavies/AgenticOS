"""
Kaizen Audit — Session Service
================================
Persists audit sessions to audit_sessions.json.
Each session maps to one client firm and one live audit call.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

AUDIT_FILE = Path(os.environ.get("AUDIT_FILE", "audit_sessions.json"))


@dataclass
class AuditSession:
    id: str
    firm_name: str
    prospect_id: str             # links to prospects.json
    client_id: str               # links to clients.json once signed
    auditor: str                 # Kane
    started_at: str
    completed_at: str = ""
    status: str = "in_progress"  # in_progress | complete | report_generated

    # Staff rates entered live
    staff_rates: Dict[str, float] = field(default_factory=lambda: {
        "partner": 40.0,
        "senior":  25.0,
        "junior":  16.0,
        "admin":   13.0,
    })

    # Active process entries (filled in during the call)
    processes: List[Dict[str, Any]] = field(default_factory=list)

    # Scores computed at submission
    scores: List[Dict[str, Any]] = field(default_factory=list)

    # Report path once generated
    report_path: str = ""
    notes: str = ""


def _load() -> List[Dict[str, Any]]:
    if not AUDIT_FILE.exists():
        return []
    with open(AUDIT_FILE) as f:
        return json.load(f)


def _save(sessions: List[Dict[str, Any]]) -> None:
    with open(AUDIT_FILE, "w") as f:
        json.dump(sessions, f, indent=2)


def create_session(
    firm_name: str,
    auditor: str = "Kane",
    prospect_id: str = "",
    client_id: str = "",
) -> AuditSession:
    session = AuditSession(
        id=f"audit_{uuid4().hex[:12]}",
        firm_name=firm_name,
        prospect_id=prospect_id,
        client_id=client_id,
        auditor=auditor,
        started_at=datetime.utcnow().isoformat(),
    )
    sessions = _load()
    sessions.append(asdict(session))
    _save(sessions)
    return session


def get_session(session_id: str) -> Optional[AuditSession]:
    for s in _load():
        if s["id"] == session_id:
            return AuditSession(**s)
    return None


def list_sessions(status: Optional[str] = None) -> List[AuditSession]:
    sessions = [AuditSession(**s) for s in _load()]
    if status:
        sessions = [s for s in sessions if s.status == status]
    return sessions


def save_processes(
    session_id: str,
    processes: List[Dict[str, Any]],
    staff_rates: Optional[Dict[str, float]] = None,
) -> Optional[AuditSession]:
    """Update the process entries on an in-progress session."""
    from .scoring import score_processes
    sessions = _load()
    for s in sessions:
        if s["id"] == session_id:
            s["processes"] = processes
            if staff_rates:
                s["staff_rates"] = staff_rates
            # Recompute scores immediately
            scored = score_processes(processes)
            s["scores"] = [asdict(sc) for sc in scored]
            _save(sessions)
            return AuditSession(**s)
    return None


def complete_session(session_id: str, notes: str = "") -> Optional[AuditSession]:
    """Mark a session as complete and ready for report generation."""
    sessions = _load()
    for s in sessions:
        if s["id"] == session_id:
            s["status"] = "complete"
            s["completed_at"] = datetime.utcnow().isoformat()
            s["notes"] = notes
            _save(sessions)
            return AuditSession(**s)
    return None


def mark_report_generated(session_id: str, report_path: str) -> Optional[AuditSession]:
    sessions = _load()
    for s in sessions:
        if s["id"] == session_id:
            s["status"] = "report_generated"
            s["report_path"] = report_path
            _save(sessions)
            return AuditSession(**s)
    return None
