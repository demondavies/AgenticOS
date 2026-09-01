"""
Phase 24+: Lead Research Engine — Prospect intelligence store.

Replaces the flat Prospect dataclass with a structured ProspectIntelligence
schema inspired by Prospector's BriefV1/ProspectIntelligenceV1 contracts.

Evidence grading:
  OBSERVED      — directly seen on their site / listing / review
  INDICATED     — strongly implied by surrounding signals
  HYPOTHESISED  — plausible inference, low direct evidence

Verdict:
  A  — Hunt    (strong signal, move now)
  B  — Watch   (potential, needs more info or timing)
  C  — Pass    (not worth pursuing right now)

Scores 0–5 per dimension; total_score is server-computed sum.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from core.db import get_db

# ---------------------------------------------------------------------------
# Sub-schemas
# ---------------------------------------------------------------------------

VALID_STRENGTHS = {"OBSERVED", "INDICATED", "HYPOTHESISED"}
VALID_VERDICTS  = {"A", "B", "C"}


@dataclass
class PainSignal:
    """A single commercial pain point with graded evidence."""
    description: str                    # What the pain is, in plain English
    evidence: str = ""                  # The raw snippet / quote / observation that grounds it
    strength: str = "INDICATED"         # OBSERVED | INDICATED | HYPOTHESISED

    def __post_init__(self):
        if self.strength not in VALID_STRENGTHS:
            self.strength = "INDICATED"


@dataclass
class OutreachIntel:
    """Angles and timing hooks for the first outreach."""
    why_now: str = ""           # Trigger or timing reason (e.g. "hiring for accounts manager")
    outreach_angle: str = ""    # The hook sentence to lead with
    objections: List[str] = field(default_factory=list)  # Likely pushbacks to pre-empt


@dataclass
class MoneyValue:
    """Typed financial value estimate for winning this prospect as a client.

    status:
      known   — we have enough signals to estimate an annual contract value
      unknown — insufficient data; do not guess
    """
    status: str = "unknown"           # "known" | "unknown"
    amount_gbp: Optional[int] = None  # Mid-point annual estimate in GBP
    range_low: Optional[int] = None   # Conservative floor
    range_high: Optional[int] = None  # Optimistic ceiling
    basis: str = ""                   # What the estimate is grounded in
    confidence: int = 0               # 0–100

    def __post_init__(self):
        if self.status not in ("known", "unknown"):
            self.status = "unknown"
        self.confidence = max(0, min(100, self.confidence))

    def display(self) -> str:
        """Human-readable summary, e.g. '£8k–£15k/yr (basis: ~10 staff)'."""
        if self.status == "unknown" or self.amount_gbp is None:
            return "UNKNOWN"
        lo = f"£{self.range_low:,}" if self.range_low else ""
        hi = f"£{self.range_high:,}" if self.range_high else ""
        mid = f"£{self.amount_gbp:,}/yr"
        rng = f" ({lo}–{hi})" if lo and hi else ""
        basis = f" — {self.basis}" if self.basis else ""
        return f"{mid}{rng}{basis}"


@dataclass
class ProspectIntelligence:
    # ── Identity ──────────────────────────────────────────────────────────
    id: str
    firm_name: str
    website: str = ""
    contact_name: str = ""
    email: str = ""
    linkedin_url: str = ""
    companies_house_number: str = ""

    # ── Verdict & confidence ───────────────────────────────────────────────
    verdict: str = "B"                  # A | B | C
    confidence: int = 0                 # 0–100: how sure we are in the verdict
    evidence_confidence: int = 0        # 0–100: quality of the underlying evidence

    # ── Business snapshot ─────────────────────────────────────────────────
    industry: str = ""
    employee_count: str = ""
    services: str = ""
    software_stack: str = ""            # Primary accounting software detected
    tech_stack: str = ""                # Broader tech/tooling mentions

    # ── Commercial thesis ─────────────────────────────────────────────────
    primary_thesis: str = ""            # One paragraph: why this firm, why now, why us
    niche: str = ""                     # Their stated specialism (e.g. "construction, contractors")

    # ── Structured pain signals ────────────────────────────────────────────
    pain_signals: List[PainSignal] = field(default_factory=list)

    # ── Scoring (0–5 per dimension; total computed on save) ───────────────
    pain_score: int = 0                 # Severity / volume of pain signals
    value_score: int = 0                # Financial value of winning this account
    urgency_score: int = 0             # How soon they need to act / we need to move
    repeatability_score: int = 0       # Potential for recurring / retainer work
    total_score: int = 0               # Server-computed: sum of the four above

    # ── Financial value estimate ──────────────────────────────────────────
    financial_value: MoneyValue = field(default_factory=MoneyValue)

    # ── Outreach intelligence ─────────────────────────────────────────────
    outreach_intel: OutreachIntel = field(default_factory=OutreachIntel)

    # ── Generated outreach drafts ─────────────────────────────────────────
    outreach_email: str = ""
    outreach_dm: str = ""

    # ── Lifecycle ─────────────────────────────────────────────────────────
    status: str = "researched"          # researched | contacted | qualified | closed | passed
    priority: str = "medium"           # high | medium | low  (derived from verdict if not set)
    researched_at: str = ""
    added_at: str = ""
    unknowns: List[str] = field(default_factory=list)
    contradictions: List[str] = field(default_factory=list)
    notes: str = ""

    def __post_init__(self):
        if self.verdict not in VALID_VERDICTS:
            self.verdict = "B"
        self.confidence         = max(0, min(100, self.confidence))
        self.evidence_confidence = max(0, min(100, self.evidence_confidence))
        self._recompute_total()

    def _recompute_total(self):
        self.total_score = (
            self.pain_score + self.value_score +
            self.urgency_score + self.repeatability_score
        )

    def verdict_label(self) -> str:
        return {"A": "Hunt", "B": "Watch", "C": "Pass"}.get(self.verdict, "Watch")


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _pain_signal_from_dict(d: dict) -> PainSignal:
    return PainSignal(
        description=d.get("description", ""),
        evidence=d.get("evidence", ""),
        strength=d.get("strength", "INDICATED"),
    )


def _money_value_from_dict(d: dict) -> MoneyValue:
    return MoneyValue(
        status=d.get("status", "unknown"),
        amount_gbp=d.get("amount_gbp"),
        range_low=d.get("range_low"),
        range_high=d.get("range_high"),
        basis=d.get("basis", ""),
        confidence=int(d.get("confidence", 0)),
    )


def _outreach_intel_from_dict(d: dict) -> OutreachIntel:
    return OutreachIntel(
        why_now=d.get("why_now", ""),
        outreach_angle=d.get("outreach_angle", ""),
        objections=d.get("objections", []),
    )


def _prospect_to_dict(p: ProspectIntelligence) -> dict:
    d = asdict(p)
    # pain_signals and outreach_intel come out as plain dicts from asdict — fine.
    return d


def _prospect_from_dict(raw: dict) -> ProspectIntelligence:
    """Deserialise a dict, upgrading flat legacy records gracefully."""
    # Pain signals: may be a list[dict] (new) or a plain string (legacy)
    raw_signals = raw.get("pain_signals", [])
    if isinstance(raw_signals, str):
        # Legacy flat string → wrap as single INDICATED signal
        signals = [PainSignal(description=raw_signals, strength="INDICATED")] if raw_signals else []
    else:
        signals = [_pain_signal_from_dict(s) for s in (raw_signals or [])]

    # Financial value: may be a dict (new) or absent (legacy)
    raw_fv = raw.get("financial_value", {})
    fv = _money_value_from_dict(raw_fv) if isinstance(raw_fv, dict) else MoneyValue()

    # Outreach intel: may be a dict (new) or absent (legacy)
    raw_oi = raw.get("outreach_intel", {})
    if isinstance(raw_oi, dict):
        oi = _outreach_intel_from_dict(raw_oi)
    else:
        oi = OutreachIntel()

    # Map legacy priority from old "medium/high" field or derive from verdict
    verdict = raw.get("verdict", "B")
    priority = raw.get("priority", "medium")
    if priority not in ("high", "medium", "low"):
        priority = {"A": "high", "B": "medium", "C": "low"}.get(verdict, "medium")

    # Legacy staff_count / software_stack aliases
    employee_count = raw.get("employee_count", "") or raw.get("staff_count", "")
    software_stack = raw.get("software_stack", "") or raw.get("tech_stack", "")

    return ProspectIntelligence(
        id=raw.get("id", f"prospect_{uuid4().hex[:8]}"),
        firm_name=raw.get("firm_name", ""),
        website=raw.get("website", ""),
        contact_name=raw.get("contact_name", ""),
        email=raw.get("email", ""),
        linkedin_url=raw.get("linkedin_url", ""),
        companies_house_number=raw.get("companies_house_number", ""),
        verdict=verdict,
        confidence=int(raw.get("confidence", 0)),
        evidence_confidence=int(raw.get("evidence_confidence", 0)),
        industry=raw.get("industry", ""),
        employee_count=employee_count,
        services=raw.get("services", ""),
        software_stack=software_stack,
        tech_stack=raw.get("tech_stack", ""),
        primary_thesis=raw.get("primary_thesis", ""),
        niche=raw.get("niche", ""),
        pain_signals=signals,
        pain_score=int(raw.get("pain_score", 0)),
        value_score=int(raw.get("value_score", 0)),
        urgency_score=int(raw.get("urgency_score", 0)),
        repeatability_score=int(raw.get("repeatability_score", 0)),
        financial_value=fv,
        outreach_intel=oi,
        outreach_email=raw.get("outreach_email", ""),
        outreach_dm=raw.get("outreach_dm", ""),
        status=raw.get("status", "researched"),
        priority=priority,
        researched_at=raw.get("researched_at", ""),
        added_at=raw.get("added_at", ""),
        notes=raw.get("notes", ""),
    )


# ---------------------------------------------------------------------------
# Store (SQLite-backed — capabilities/prospects table in kaido.db)
# ---------------------------------------------------------------------------

def load_prospects() -> list[ProspectIntelligence]:
    """Load every prospect, most-recently-created first."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT data FROM prospects ORDER BY created_at DESC"
        ).fetchall()
    finally:
        conn.close()
    return [_prospect_from_dict(json.loads(row["data"])) for row in rows]


def delete_prospect(prospect_id: str) -> None:
    """Permanently remove a prospect record by ID."""
    conn = get_db()
    try:
        conn.execute("DELETE FROM prospects WHERE id = ?", (prospect_id,))
        conn.commit()
    finally:
        conn.close()


def save_prospect(prospect: ProspectIntelligence) -> None:
    """Upsert a single prospect record."""
    prospect._recompute_total()
    county = getattr(prospect, "location", "") or None
    conn = get_db()
    try:
        conn.execute(
            """
            INSERT INTO prospects
                (id, firm_name, website, verdict, status, confidence,
                 total_score, county, updated_at, data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?)
            ON CONFLICT(id) DO UPDATE SET
                firm_name=excluded.firm_name,
                website=excluded.website,
                verdict=excluded.verdict,
                status=excluded.status,
                confidence=excluded.confidence,
                total_score=excluded.total_score,
                county=excluded.county,
                updated_at=excluded.updated_at,
                data=excluded.data
            """,
            (
                prospect.id,
                prospect.firm_name,
                prospect.website,
                prospect.verdict,
                prospect.status,
                prospect.confidence,
                prospect.total_score,
                county,
                json.dumps(_prospect_to_dict(prospect)),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def save_prospects(prospects: list[ProspectIntelligence]) -> None:
    """Upsert a batch of prospect records."""
    for p in prospects:
        save_prospect(p)


# Internal aliases used throughout this module.
_load = load_prospects
_save = save_prospects


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def add_prospect(
    firm_name: str,
    website: str = "",
    employee_count: str = "",
    services: str = "",
    software_stack: str = "",
    tech_stack: str = "",
    companies_house_number: str = "",
    # Intelligence fields
    verdict: str = "B",
    confidence: int = 30,
    evidence_confidence: int = 20,
    primary_thesis: str = "",
    niche: str = "",
    pain_signals: Optional[List[PainSignal]] = None,
    pain_score: int = 0,
    value_score: int = 0,
    urgency_score: int = 0,
    repeatability_score: int = 0,
    outreach_intel: Optional[OutreachIntel] = None,
    financial_value: Optional[MoneyValue] = None,
    # Legacy compat
    staff_count: str = "",
    notes: str = "",
    priority: str = "",
    unknowns: Optional[List[str]] = None,
    contradictions: Optional[List[str]] = None,
) -> ProspectIntelligence:
    prospects = _load()
    prospect_id = f"prospect_{int(datetime.now(timezone.utc).timestamp())}_{uuid4().hex[:6]}"

    # Derive priority from verdict if not explicitly set
    if not priority:
        priority = {"A": "high", "B": "medium", "C": "low"}.get(verdict, "medium")

    now = datetime.now(timezone.utc).isoformat()
    prospect = ProspectIntelligence(
        id=prospect_id,
        firm_name=firm_name,
        website=website,
        employee_count=employee_count or staff_count,
        services=services,
        software_stack=software_stack,
        tech_stack=tech_stack,
        companies_house_number=companies_house_number,
        verdict=verdict,
        confidence=confidence,
        evidence_confidence=evidence_confidence,
        primary_thesis=primary_thesis,
        niche=niche,
        pain_signals=pain_signals or [],
        pain_score=pain_score,
        value_score=value_score,
        urgency_score=urgency_score,
        repeatability_score=repeatability_score,
        financial_value=financial_value or MoneyValue(),
        outreach_intel=outreach_intel or OutreachIntel(),
        unknowns=unknowns or [],
        contradictions=contradictions or [],
        status="researched",
        priority=priority,
        researched_at=now,
        added_at=now,
        notes=notes,
    )
    prospects.append(prospect)
    _save(prospects)
    return prospect


def list_prospects(status: Optional[str] = None) -> list[ProspectIntelligence]:
    prospects = _load()
    if status:
        prospects = [p for p in prospects if p.status == status]
    # Default sort: A verdicts first, then by total_score desc
    prospects.sort(key=lambda p: (p.verdict, -p.total_score))
    return prospects


def get_prospect(prospect_id: str) -> Optional[ProspectIntelligence]:
    for p in _load():
        if p.id == prospect_id:
            return p
    return None


def get_prospect_by_name(name: str) -> Optional[ProspectIntelligence]:
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
) -> Optional[ProspectIntelligence]:
    prospects = _load()
    for p in prospects:
        if p.id == prospect_id:
            p.status = status
            if notes:
                p.notes = notes
            _save(prospects)
            return p
    return None


def update_prospect_intel(
    prospect_id: str,
    verdict: Optional[str] = None,
    firm_name: Optional[str] = None,
    confidence: Optional[int] = None,
    evidence_confidence: Optional[int] = None,
    primary_thesis: Optional[str] = None,
    pain_signals: Optional[List[PainSignal]] = None,
    pain_score: Optional[int] = None,
    value_score: Optional[int] = None,
    urgency_score: Optional[int] = None,
    repeatability_score: Optional[int] = None,
    outreach_intel: Optional[OutreachIntel] = None,
    financial_value: Optional[MoneyValue] = None,
    notes: Optional[str] = None,
    niche: Optional[str] = None,
    software_stack: Optional[str] = None,
    companies_house_number: Optional[str] = None,
    unknowns: Optional[List[str]] = None,
    contradictions: Optional[List[str]] = None,
) -> Optional[ProspectIntelligence]:
    """Patch intelligence fields on an existing prospect."""
    prospects = _load()
    for p in prospects:
        if p.id == prospect_id:
            if firm_name is not None:
                # Prefer the shorter/cleaner name
                if len(firm_name) < len(p.firm_name):
                    p.firm_name = firm_name
            if verdict is not None:            p.verdict = verdict
            if confidence is not None:         p.confidence = confidence
            if evidence_confidence is not None: p.evidence_confidence = evidence_confidence
            if primary_thesis is not None:     p.primary_thesis = primary_thesis
            if pain_signals is not None:       p.pain_signals = pain_signals
            if pain_score is not None:         p.pain_score = pain_score
            if value_score is not None:        p.value_score = value_score
            if urgency_score is not None:      p.urgency_score = urgency_score
            if repeatability_score is not None: p.repeatability_score = repeatability_score
            if financial_value is not None:    p.financial_value = financial_value
            if outreach_intel is not None:     p.outreach_intel = outreach_intel
            if notes is not None:              p.notes = notes
            if niche is not None:              p.niche = niche
            if software_stack is not None:     p.software_stack = software_stack
            if companies_house_number is not None: p.companies_house_number = companies_house_number
            if unknowns is not None:           p.unknowns = unknowns
            if contradictions is not None:     p.contradictions = contradictions
            # Derive priority from updated verdict
            p.priority = {"A": "high", "B": "medium", "C": "low"}.get(p.verdict, "medium")
            _save(prospects)
            return p
    return None


def save_outreach(
    prospect_id: str,
    outreach_email: str = "",
    outreach_dm: str = "",
) -> Optional[ProspectIntelligence]:
    """Store generated outreach drafts against a prospect record."""
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
