"""One-time migration: prospects.json -> kaido.db (prospects table).

Standalone script, not imported by bot.py. Leaves prospects.json in place —
delete it manually once the migration is verified.
"""
import json
from pathlib import Path

from core.db import init_db
from capabilities.prospects.service import save_prospect, _prospect_from_dict

PROSPECTS_JSON = Path("prospects.json")


def main() -> None:
    init_db()

    if not PROSPECTS_JSON.exists():
        print("No prospects.json found — nothing to migrate.")
        return

    with open(PROSPECTS_JSON, "r", encoding="utf-8") as f:
        raw = json.load(f)

    count = 0
    for entry in raw:
        prospect = _prospect_from_dict(entry)
        save_prospect(prospect)
        count += 1

    print(f"Migrated {count} prospect(s) from prospects.json into kaido.db.")


if __name__ == "__main__":
    main()
