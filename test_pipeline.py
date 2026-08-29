"""
Kaizen OS Pipeline Test
=======================
Tests the Scout → Pitch pipeline end-to-end without Discord or Policy.
Calls harness execute_* methods directly — for development testing only.

Requirements:
    Ollama running with hermes3:8b loaded

Usage:
    python test_pipeline.py [firm_name] [website]

Examples:
    python test_pipeline.py
    python test_pipeline.py "Thornbury & Partners" "thornburyaccountants.co.uk"
    python test_pipeline.py "Maxx Landscaping" "maxxlandscaping.co.uk"
"""

import asyncio
import json
import sys

from core.tools import create_default_registry
from core.harness import AgentHarness
from capabilities.voice import VoiceService


async def run_pipeline(firm_name: str, website: str = "") -> None:
    sep = "=" * 60
    print(f"\n{sep}")
    print("  KAIZEN OS PIPELINE TEST")
    print(f"  Firm   : {firm_name}")
    print(f"  Website: {website or '(none)'}")
    print(sep)

    # Boot the harness
    registry = create_default_registry()
    harness = AgentHarness(
        tool_registry=registry,
        voice_service=VoiceService(),
    )
    print("✓ Harness booted\n")

    # ── PHASE 24: Scout researches the firm ──────────────────────────────────
    print("[SCOUT] Researching firm...")
    print("-" * 40)
    try:
        research_result = await harness.execute_research_prospect(
            firm_name=firm_name,
            website=website,
        )
        print(research_result)
    except Exception as exc:
        print(f"✗ Research failed: {exc}")
        return

    # Grab the prospect ID from prospects.json
    try:
        with open("prospects.json") as f:
            prospects = json.load(f)
        if not prospects:
            print("✗ No prospects found in prospects.json")
            return
        prospect = prospects[-1]
        prospect_id = prospect["id"]
        print(f"\n✓ Prospect saved: {prospect_id}")
        print(f"  Name   : {prospect.get('firm_name')}")
        print(f"  Stack  : {prospect.get('software_stack')}")
        print(f"  Pain   : {prospect.get('pain_signals')}")
        print(f"  Priority: {prospect.get('priority')}")
    except FileNotFoundError:
        print("✗ prospects.json not found — research failed silently")
        return

    # ── PHASE 24: List all prospects ────────────────────────────────────────
    print("\n[SCOUT] Prospect store summary:")
    print("-" * 40)
    list_result = await harness.execute_list_prospects(status=None)
    print(list_result)

    # ── PHASE 25: Pitch drafts outreach ─────────────────────────────────────
    print(f"\n[PITCH] Drafting outreach for {prospect_id}...")
    print("-" * 40)
    try:
        outreach_result = await harness.execute_draft_outreach(
            prospect_id=prospect_id,
        )
        print(outreach_result)
    except Exception as exc:
        print(f"✗ Outreach draft failed: {exc}")
        return

    print(f"\n{sep}")
    print("  PIPELINE COMPLETE")
    print(f"  Check prospects.json for saved data")
    print(sep)


if __name__ == "__main__":
    firm = sys.argv[1] if len(sys.argv) > 1 else "Thornbury & Partners Accountants"
    site = sys.argv[2] if len(sys.argv) > 2 else "thornburyaccountants.co.uk"
    asyncio.run(run_pipeline(firm, site))
