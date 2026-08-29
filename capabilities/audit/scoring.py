"""
Kaizen Audit — Scoring Engine
==============================
Calculates Quick Win scores for each active process during a live audit.

Scoring formula:
    time_cost_monthly = (time_mins / 60) × hourly_rate × frequency_per_month
    volume_score      = 1–5 derived from time_cost_monthly
    quick_win         = (automation_potential × volume_score) / risk

Higher quick_win = build first. Processes scoring ≥ 12 are flagged as
Priority Quick Wins. Processes with automation_potential ≤ 2 or risk == 5
are flagged as Leave Alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


STAFF_RATE_DEFAULTS = {
    "partner":  40,   # £/hr — ~£73k salary
    "senior":   25,   # £/hr — ~£46k salary
    "junior":   16,   # £/hr — ~£29k salary
    "admin":    13,   # £/hr — ~£24k salary
}


@dataclass
class ProcessScore:
    process_id: str
    process_name: str
    automation_potential: int    # 1–5 (Kane-adjusted or base)
    risk: int                    # 1–5 (Kane-adjusted or base)
    time_mins: int               # per instance
    frequency_per_month: float   # instances per month
    hourly_rate: float           # £/hr for the staff member doing it
    staff_role: str

    # Computed
    time_cost_monthly: float = 0.0   # £/month if done manually
    volume_score: int = 0            # 1–5 derived from time cost
    quick_win_score: float = 0.0
    flag: str = ""                   # "quick_win" | "leave_alone" | ""
    annual_saving_estimate: float = 0.0  # assuming 80% time reduction

    def __post_init__(self) -> None:
        self._compute()

    def _compute(self) -> None:
        self.time_cost_monthly = (
            (self.time_mins / 60) * self.hourly_rate * self.frequency_per_month
        )

        # Volume score: £0–50/mo=1, £50–150=2, £150–400=3, £400–1000=4, £1000+=5
        if self.time_cost_monthly < 50:
            self.volume_score = 1
        elif self.time_cost_monthly < 150:
            self.volume_score = 2
        elif self.time_cost_monthly < 400:
            self.volume_score = 3
        elif self.time_cost_monthly < 1000:
            self.volume_score = 4
        else:
            self.volume_score = 5

        if self.risk == 0:
            self.quick_win_score = 0.0
        else:
            self.quick_win_score = round(
                (self.automation_potential * self.volume_score) / self.risk, 2
            )

        self.annual_saving_estimate = round(
            self.time_cost_monthly * 12 * 0.8, 2
        )

        if self.automation_potential <= 2 or self.risk == 5:
            self.flag = "leave_alone"
        elif self.quick_win_score >= 12:
            self.flag = "quick_win"
        else:
            self.flag = ""


def score_processes(process_entries: List[dict]) -> List[ProcessScore]:
    """
    Score a list of active process entries from the audit form.

    Each entry dict:
        process_id, process_name, automation_potential, risk,
        time_mins, frequency_per_month, hourly_rate, staff_role
    """
    scores = []
    for entry in process_entries:
        score = ProcessScore(
            process_id=entry["process_id"],
            process_name=entry["process_name"],
            automation_potential=int(entry.get("automation_potential", 3)),
            risk=int(entry.get("risk", 3)),
            time_mins=int(entry.get("time_mins", 30)),
            frequency_per_month=float(entry.get("frequency_per_month", 4)),
            hourly_rate=float(entry.get("hourly_rate", 25)),
            staff_role=entry.get("staff_role", "senior"),
        )
        scores.append(score)

    # Sort: quick wins first, then by score descending
    scores.sort(key=lambda s: (-s.quick_win_score, s.process_id))
    return scores


def top_quick_wins(scores: List[ProcessScore], n: int = 3) -> List[ProcessScore]:
    """Return the top N quick win processes."""
    return [s for s in scores if s.flag == "quick_win"][:n]


def total_monthly_cost(scores: List[ProcessScore]) -> float:
    """Total manual time cost per month across all scored processes."""
    return round(sum(s.time_cost_monthly for s in scores), 2)


def total_annual_saving_estimate(scores: List[ProcessScore]) -> float:
    """Estimated annual saving if all quick wins are automated (80% reduction)."""
    return round(
        sum(s.annual_saving_estimate for s in scores if s.flag == "quick_win"), 2
    )
