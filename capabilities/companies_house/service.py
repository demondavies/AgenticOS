"""
Companies House lookup — real filing/incorporation facts for prospect scoring.

Free public API (register a key at https://developer.companieshouse.gov.uk).
Auth: HTTP Basic, username = API key, password = "" (empty).
Docs: https://developer-specs.company-information.service.gov.uk/

No key configured, no confident match, or any request failure → lookup_company()
returns None and callers fall back to their existing (website-inferred) scoring.
"""
from __future__ import annotations

import difflib
import logging
import os
import re
import time
from datetime import date, datetime, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://api.companieshouse.gov.uk"
API_KEY = os.getenv("COMPANIES_HOUSE_API_KEY", "")

_TIMEOUT = 10
_RATE_LIMIT_DELAY = 0.5  # free tier limit — one call at a time, spaced out

# Company types that aren't the UK domestic company we're scoring as a
# prospect (overseas entities filing a UK presence, not a UK-run practice).
_EXCLUDED_COMPANY_TYPES = {
    "oversea-company",
    "registered-overseas-entity",
}

# Below this ratio, the top search hit is treated as too weak to trust —
# same as no match found.
_NAME_SIMILARITY_THRESHOLD = 0.45

# Private-company statutory deadline: accounts due 9 months after the
# accounting reference period ends. Used to detect late filings in the
# history feed, which has no explicit "late" flag of its own.
_STATUTORY_ACCOUNTS_WINDOW_DAYS = 274


def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def _name_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _normalize_name(a), _normalize_name(b)).ratio()


def _get(session: requests.Session, path: str, params: Optional[dict] = None) -> Optional[dict]:
    try:
        resp = session.get(
            f"{BASE_URL}{path}",
            params=params,
            auth=(API_KEY, ""),
            timeout=_TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        return resp.json()
    except requests.exceptions.RequestException as err:
        logger.warning("CH lookup: request failed (%s): %s", path, err)
        return None


def _pick_best_match(firm_name: str, items: list[dict]) -> Optional[dict]:
    candidates = [
        item for item in items
        if item.get("company_status") == "active"
        and item.get("company_type") not in _EXCLUDED_COMPANY_TYPES
    ]
    if not candidates:
        return None

    best = max(candidates, key=lambda item: _name_similarity(firm_name, item.get("title", "")))
    if _name_similarity(firm_name, best.get("title", "")) < _NAME_SIMILARITY_THRESHOLD:
        return None
    return best


def _late_filing_detected(filing_history: Optional[dict]) -> tuple[bool, str]:
    """Returns (detected, filed_date_iso) for the most recent late accounts filing."""
    if not filing_history or not filing_history.get("items"):
        return False, ""

    cutoff = date.today() - timedelta(days=3 * 365)
    latest_late: Optional[date] = None
    for item in filing_history["items"]:
        if item.get("category") != "accounts":
            continue
        filed_raw = item.get("date")
        made_up_to_raw = (item.get("description_values") or {}).get("made_up_date")
        if not filed_raw or not made_up_to_raw:
            continue
        try:
            filed_date = datetime.strptime(filed_raw, "%Y-%m-%d").date()
            made_up_to = datetime.strptime(made_up_to_raw, "%Y-%m-%d").date()
        except ValueError:
            continue
        if filed_date < cutoff:
            continue
        statutory_due = made_up_to + timedelta(days=_STATUTORY_ACCOUNTS_WINDOW_DAYS)
        if filed_date > statutory_due and (latest_late is None or filed_date > latest_late):
            latest_late = filed_date

    if latest_late:
        return True, latest_late.isoformat()
    return False, ""


def _extract_facts(company_number: str, profile: dict, filing_history: Optional[dict]) -> dict:
    accounts = profile.get("accounts", {}) or {}
    last_accounts = accounts.get("last_accounts", {}) or {}
    currently_overdue = bool(accounts.get("overdue"))

    late_detected, late_date = _late_filing_detected(filing_history)
    if currently_overdue:
        late_detected = True
        late_date = late_date or accounts.get("next_due", "")

    # CH's public API doesn't expose a headcount figure on the standard
    # company profile — this reads it defensively in case it's ever present,
    # and otherwise leaves employee_count empty so callers fall back to the
    # existing website-based staff inference, per the fallback rule.
    employee_count = profile.get("employee_count") or last_accounts.get("employee_count")

    return {
        "company_number": company_number,
        "company_name": profile.get("company_name", ""),
        "company_status": profile.get("company_status", ""),
        "date_of_creation": profile.get("date_of_creation", ""),
        "registered_office_address": profile.get("registered_office_address", {}) or {},
        "accounts_made_up_to": last_accounts.get("made_up_to", ""),
        "accounts_next_due": accounts.get("next_due", ""),
        "employee_count": employee_count,
        "late_filing_detected": late_detected,
        "late_filing_date": late_date,
    }


def lookup_company(firm_name: str) -> Optional[dict]:
    """Resolve a UK firm name to Companies House facts.

    Synchronous (uses `requests`) — call via `asyncio.to_thread` from async
    code so it doesn't block the event loop. Returns None (never raises) if
    no API key is configured, no confident match is found, or any request
    fails — callers should treat that as "fall back to existing scoring".
    """
    if not API_KEY or not firm_name:
        return None

    with requests.Session() as session:
        search = _get(session, "/search/companies", {"q": firm_name, "items_per_page": 5})
        items = (search or {}).get("items") or []
        match = _pick_best_match(firm_name, items)
        if not match:
            logger.info("CH lookup: no match for %s", firm_name)
            return None

        company_number = match.get("company_number")
        if not company_number:
            logger.info("CH lookup: no match for %s", firm_name)
            return None

        time.sleep(_RATE_LIMIT_DELAY)
        profile = _get(session, f"/company/{company_number}")
        if not profile:
            logger.info("CH lookup: no match for %s", firm_name)
            return None

        time.sleep(_RATE_LIMIT_DELAY)
        filing_history = _get(
            session,
            f"/company/{company_number}/filing-history",
            {"category": "accounts", "items_per_page": 5},
        )

        logger.info("CH lookup: found %s for %s", company_number, firm_name)
        return _extract_facts(company_number, profile, filing_history)
