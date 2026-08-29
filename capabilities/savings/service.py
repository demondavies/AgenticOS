"""
Phase 26: Savings Baseline Logger — before-state process cost store.

Stores Kaizen Studios client process baselines (time per run, frequency,
staff cost) in savings_baselines.json at the project root, following the
same pattern as capabilities/clients/service.py and
capabilities/prospects/service.py.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

SAVINGS_BASELINES_FILE = Path(
    os.environ.get("SAVINGS_BASELINES_FILE", "savings_baselines.json")
)


@dataclass
class SavingsBaseline:
    id: str
    client_id: str
    process_name: str
    minutes_per_run: float
    runs_per_month: float
    staff_hourly_rate: float
    baseline_monthly_cost: float
    logged_at: str
    notes: str = ""


def _load() -> list[SavingsBaseline]:
    if not SAVINGS_BASELINES_FILE.exists():
        return []
    with open(SAVINGS_BASELINES_FILE, "r", encoding="utf-8") as f:
        return [SavingsBaseline(**b) for b in json.load(f)]


def _save(baselines: list[SavingsBaseline]) -> None:
    with open(SAVINGS_BASELINES_FILE, "w", encoding="utf-8") as f:
        json.dump([asdict(b) for b in baselines], f, indent=2)


def log_baseline(
    client_id: str,
    process_name: str,
    minutes_per_run: float,
    runs_per_month: float,
    staff_hourly_rate: float,
    notes: str = "",
) -> SavingsBaseline:
    baselines = _load()
    baseline_id = f"baseline_{int(datetime.now(timezone.utc).timestamp())}_{uuid4().hex[:6]}"
    baseline_monthly_cost = (
        (minutes_per_run * runs_per_month) / 60.0
    ) * staff_hourly_rate
    baseline = SavingsBaseline(
        id=baseline_id,
        client_id=client_id,
        process_name=process_name,
        minutes_per_run=minutes_per_run,
        runs_per_month=runs_per_month,
        staff_hourly_rate=staff_hourly_rate,
        baseline_monthly_cost=baseline_monthly_cost,
        logged_at=datetime.now(timezone.utc).isoformat(),
        notes=notes,
    )
    baselines.append(baseline)
    _save(baselines)
    return baseline


def list_baselines(client_id: str | None = None) -> list[SavingsBaseline]:
    baselines = _load()
    if client_id:
        baselines = [b for b in baselines if b.client_id == client_id]
    return baselines


def get_baseline(baseline_id: str) -> SavingsBaseline | None:
    for b in _load():
        if b.id == baseline_id:
            return b
    return None
