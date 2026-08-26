"""AgenticOS local time capability."""

from __future__ import annotations

from datetime import datetime


def get_current_time() -> str:
    """Return the local system date and time."""
    now = datetime.now()
    return (
        f"The current local system time is {now.strftime('%I:%M %p')} "
        f"and the date is {now.strftime('%A, %B %d, %Y')}."
    )
