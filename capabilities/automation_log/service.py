"""
Phase 27: Automation Activity Logger — records each automation run and
tallies minutes/money saved against the client's logged Savings Baseline.

Stores runs in automation_runs.json at the project root, following the
same pattern as capabilities/clients/service.py and
capabilities/savings/service.py.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from capabilities.savings.service import get_baseline

AUTOMATION_RUNS_FILE = Path(
    os.environ.get("AUTOMATION_RUNS_FILE", "automation_runs.json")
)


@dataclass
class AutomationRun:
    id: str
    client_id: str
    process_name: str
    baseline_id: str
    ran_at: str
    duration_seconds: float
    minutes_saved: float
    notes: str = ""


def _load() -> list[AutomationRun]:
    if not AUTOMATION_RUNS_FILE.exists():
        return []
    with open(AUTOMATION_RUNS_FILE, "r", encoding="utf-8") as f:
        return [AutomationRun(**r) for r in json.load(f)]


def _save(runs: list[AutomationRun]) -> None:
    with open(AUTOMATION_RUNS_FILE, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in runs], f, indent=2)


def log_run(
    client_id: str,
    process_name: str,
    baseline_id: str,
    duration_seconds: float,
    notes: str = "",
) -> AutomationRun:
    """Record one automation run, computing minutes saved against its baseline.

    minutes_saved = baseline.minutes_per_run - (duration_seconds / 60). If the
    referenced baseline can't be found, minutes_saved is recorded as 0.0 rather
    than failing the run log — the raw run is still worth keeping.
    """
    baseline = get_baseline(baseline_id)
    minutes_saved = 0.0
    if baseline is not None:
        minutes_saved = baseline.minutes_per_run - (duration_seconds / 60.0)

    runs = _load()
    run_id = f"run_{int(datetime.now(timezone.utc).timestamp())}_{uuid4().hex[:6]}"
    run = AutomationRun(
        id=run_id,
        client_id=client_id,
        process_name=process_name,
        baseline_id=baseline_id,
        ran_at=datetime.now(timezone.utc).isoformat(),
        duration_seconds=duration_seconds,
        minutes_saved=minutes_saved,
        notes=notes,
    )
    runs.append(run)
    _save(runs)
    return run


def list_runs(
    client_id: str,
    since_date: str | None = None,
) -> list[AutomationRun]:
    runs = [r for r in _load() if r.client_id == client_id]
    if since_date:
        runs = [r for r in runs if r.ran_at >= since_date]
    return runs


def monthly_summary(client_id: str, year: int, month: int) -> dict:
    """Tally runs, minutes saved, and £ saved for one client/month."""
    month_runs = [
        r
        for r in list_runs(client_id)
        if _parse_year_month(r.ran_at) == (year, month)
    ]

    tally = _tally_runs(month_runs)
    return {
        "client_id": client_id,
        "year": year,
        "month": month,
        **tally,
    }


def total_savings_to_date(client_id: str) -> dict:
    """Tally all-time runs, minutes saved, and £ saved for one client.

    Unlike monthly_summary, this is not scoped to a single calendar month —
    it's a running lifetime total, used by the Phase 29 client dashboard.
    """
    tally = _tally_runs(list_runs(client_id))
    return {
        "client_id": client_id,
        **tally,
    }


def _tally_runs(runs: list[AutomationRun]) -> dict:
    """Shared aggregation used by monthly_summary and total_savings_to_date.

    £ saved is cross-referenced per-run against that run's own baseline
    hourly rate (not a single client-wide rate), since a client may have
    multiple processes automated at different baseline costs.
    """
    total_runs = len(runs)
    total_minutes_saved = sum(r.minutes_saved for r in runs)

    baseline_cache: dict[str, object] = {}
    total_gbp_saved = 0.0
    for run in runs:
        if run.baseline_id not in baseline_cache:
            baseline_cache[run.baseline_id] = get_baseline(run.baseline_id)
        baseline = baseline_cache[run.baseline_id]
        if baseline is not None:
            total_gbp_saved += (run.minutes_saved / 60.0) * baseline.staff_hourly_rate

    return {
        "total_runs": total_runs,
        "total_minutes_saved": round(total_minutes_saved, 2),
        "total_gbp_saved": round(total_gbp_saved, 2),
    }


def _parse_year_month(iso_timestamp: str) -> tuple[int, int]:
    dt = datetime.fromisoformat(iso_timestamp)
    return (dt.year, dt.month)
