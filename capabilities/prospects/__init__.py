"""Phase 24: Lead Research Engine — prospect capability exports."""

from capabilities.prospects.service import (
    add_prospect,
    list_prospects,
    get_prospect,
    update_prospect_status,
    save_outreach,
    Prospect,
)

__all__ = [
    "add_prospect",
    "list_prospects",
    "get_prospect",
    "update_prospect_status",
    "save_outreach",
    "Prospect",
]
