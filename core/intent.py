from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass(frozen=True)
class Intent:
    """Deterministic interpretation of an incoming user request."""

    tool_name: Optional[str] = None
    arguments: Dict[str, str] = field(default_factory=dict)


class IntentRouter:
    """
    Canonical deterministic intent router.

    The router identifies obvious local capabilities before the LLM gets a
    chance to answer from general knowledge.
    """

    def route(self, content: str, *, is_owner: bool = True) -> Intent:
        clean = (content or "").strip()
        lower = clean.lower()

        if not clean or not is_owner:
            return Intent()

        # ------------------------------------------------------------
        # CURRENT TIME / DATE
        # ------------------------------------------------------------
        if (
            re.search(
                r"\b(?:time\s+and\s+date|date\s+and\s+time)\b",
                lower,
            )
            or re.search(
                r"\b(?:what(?:'s| is)|tell me|give me|show me)"
                r"\s+(?:the\s+)?(?:current\s+)?(?:time|date)\b",
                lower,
            )
            or re.fullmatch(
                r"(?:what(?:'s| is)\s+)?(?:the\s+)?"
                r"(?:current\s+)?(?:time|date)",
                lower,
            )
        ):
            return Intent(
                tool_name="get_current_time"
            )

        # ------------------------------------------------------------
        # SYSTEM METRICS
        # ------------------------------------------------------------
        if re.search(
            r"\b(?:system\s+metrics|hardware\s+metrics|"
            r"system\s+telemetry|hardware\s+telemetry)\b",
            lower,
        ) or (
            "cpu" in lower
            and ("ram" in lower or "memory" in lower)
        ):
            return Intent(
                tool_name="get_system_metrics"
            )

        # ------------------------------------------------------------
        # DAILY / MASTER BRAIN VAULT SUMMARY
        # ------------------------------------------------------------
        if re.search(
            r"\b(?:daily|today(?:'s)?|current)\s+"
            r"(?:master\s+brain\s+)?vault\s+summary\b|"
            r"\b(?:master\s+brain|vault)\s+summary\b",
            lower,
        ):
            return Intent(
                tool_name="get_daily_vault_summary",
                arguments={},
            )

        # ------------------------------------------------------------
        # VAULT SEARCH
        #
        # Examples:
        #   Search my vault for AgenticOS
        #   Search the vault for AgenticOS
        #   Search Master Brain for AgenticOS
        #   Find AgenticOS in my vault
        #   Look inside my vault for AgenticOS
        # ------------------------------------------------------------
        vault_search = re.search(
            r"\b(?:search|find|look\s+(?:up|for)|look\s+inside)\b"
            r".*?"
            r"\b(?:my\s+)?(?:master\s+brain|vault)\b"
            r"(?:\s+for|\s+about|\s+regarding)?\s*(.*)$",
            clean,
            flags=re.IGNORECASE,
        )

        if vault_search:
            query = vault_search.group(1).strip(" ?.")

            # Handle "Find AgenticOS in my vault"
            if not query:
                reverse_match = re.search(
                    r"^(?:search|find|look\s+(?:up|for))\s+"
                    r"(.+?)\s+(?:in|inside|within)\s+"
                    r"(?:my\s+)?(?:master\s+brain|vault)\s*$",
                    clean,
                    flags=re.IGNORECASE,
                )

                if reverse_match:
                    query = reverse_match.group(1).strip(" ?.")

            return Intent(
                tool_name="search_vault",
                arguments={
                    "query": query or clean
                },
            )

        # ------------------------------------------------------------
        # LOCAL APPLICATION LAUNCH
        #
        # The router identifies obvious application-launch requests.
        # Policy/Harness remains responsible for authorization.
        # ------------------------------------------------------------
        app_match = re.search(
            r"\b(?:open|launch|start|run)\s+"
            r"(?:the\s+)?(?:app|application|program|software)\s+"
            r"(.+?)(?:\s*[?.!]\s*)?$",
            clean,
            flags=re.IGNORECASE,
        )

        if not app_match:
            app_match = re.search(
                r"\b(?:open|launch|start|run)\s+"
                r"(?:the\s+)?"
                r"(notepad|calculator|calc|chrome|google\s+chrome|"
                r"obsidian|vscode|vs\s*code|code|terminal|windows\s+terminal|"
                r"cmd|command\s+prompt|explorer|file\s+explorer)"
                r"(?:\s*[?.!]\s*)?$",
                clean,
                flags=re.IGNORECASE,
            )

        if app_match:
            target = app_match.group(1).strip()

            target = re.sub(
                r"^(?:the\s+)?(?:app|application|program|software)\s+",
                "",
                target,
                flags=re.IGNORECASE,
            ).strip()

            aliases = {
                "google chrome": "chrome",
                "vs code": "vscode",
                "windows terminal": "terminal",
                "command prompt": "cmd",
                "file explorer": "explorer",
                "calculator": "calc",
            }
            target = aliases.get(target.lower(), target)

            # Normalize known application aliases and canonical targets so
            # deterministic intent routing remains stable regardless of
            # capitalization in the user's request.
            canonical_targets = {
                "notepad": "Notepad",
                "calc": "calc",
                "chrome": "chrome",
                "vscode": "vscode",
                "obsidian": "obsidian",
                "terminal": "terminal",
                "cmd": "cmd",
                "explorer": "explorer",
            }
            target = canonical_targets.get(target.lower(), target)

            return Intent(
                tool_name="launch_app",
                arguments={"target": target},
            )

        # ------------------------------------------------------------
        # READ OBSIDIAN NOTE
        #
        # Examples:
        #   Read my Inbox note
        #   Read Inbox
        #   Open my Inbox note
        #   Read my Project note
        #   Show me Inbox.md
        # ------------------------------------------------------------
        if re.search(
            r"\b(?:read|open|show|display|look\s+at)\b",
            lower,
        ) and re.search(
            r"\b(?:my\s+)?(?:inbox|note|notes?|"
            r"markdown|\.md)\b",
            lower,
        ):
            if re.search(r"\binbox\b", lower):
                filename = "Inbox"
            else:
                note_match = re.search(
                    r"\b(?:my\s+)?(?:note|file)\s+"
                    r"([A-Za-z0-9_. -]+?)"
                    r"(?:\s+note)?\s*[?.!]?$",
                    clean,
                    flags=re.IGNORECASE,
                )

                filename = (
                    note_match.group(1).strip()
                    if note_match
                    else "Inbox"
                )

            return Intent(
                tool_name="read_obsidian_note",
                arguments={
                    "filename": filename
                },
            )

        # ------------------------------------------------------------
        # WEB SEARCH
        #
        # Examples:
        #   Search the web for the latest Ollama release
        #   Search the internet for Ollama
        #   Look up the latest Ollama release
        #   Find the latest Ollama release
        # ------------------------------------------------------------
        if re.search(
            r"\b(?:search|look\s+(?:up|for)|find)\b",
            lower,
        ) and (
            re.search(
                r"\b(?:web|internet|online)\b",
                lower,
            )
            or re.search(
                r"\b(?:latest|news|release|version|current)\b",
                lower,
            )
        ):
            query = clean

            query = re.sub(
                r"^\s*(?:please\s+)?"
                r"(?:search|look\s+(?:up|for)|find)\s+"
                r"(?:the\s+)?"
                r"(?:web|internet|online)\s*"
                r"(?:for\s+)?",
                "",
                query,
                flags=re.IGNORECASE,
            ).strip(" ?.")

            if not query:
                query = clean

            return Intent(
                tool_name="web_search",
                arguments={
                    "query": query
                },
            )

        # ------------------------------------------------------------
        # IMAGE GENERATION
        # ------------------------------------------------------------
        img_match = re.search(
            r"\b(?:generate|create|make|draw|produce)\s+(?:an?\s+)?image\s+(?:of\s+)?(.+)",
            lower,
        )
        if img_match:
            prompt_text = clean[img_match.start(1):]
            return Intent(
                tool_name="generate_image",
                arguments={"prompt": prompt_text.strip()},
            )

        # ------------------------------------------------------------
        # LIST TASKS
        # ------------------------------------------------------------
        if re.search(
            r"\b(?:list|show|what(?:'s| are)|display)\s+(?:(?:my|all|current|active|running)\s+)?tasks?\b"
            r"|\btask\s+queue\b"
            r"|\bwhat(?:'s| is)\s+(?:arnie\s+)?(?:working\s+on|running)\b",
            lower,
        ):
            return Intent(tool_name="list_tasks")

        # ------------------------------------------------------------
        # PARALLEL AGENCY RESEARCH
        # ------------------------------------------------------------
        parallel_match = re.search(
            r"\b(?:parallel|simultaneously|at once|fan.?out)\b.*"
            r"\b(?:research|agency|tasks?)\b",
            lower,
        )
        if parallel_match:
            return Intent(tool_name="run_parallel_agency", arguments={"topics": []})

        # ------------------------------------------------------------
        # AGENCY RESEARCH
        # ------------------------------------------------------------
        agency_match = re.search(
            r"\b(?:agency\s+research\s+(?:on|about)|research\s+(?:on|about|the\s+company|the\s+topic)\s+)(.+)",
            lower,
        )
        if agency_match:
            topic_text = clean[agency_match.start(1):]
            return Intent(
                tool_name="run_agency_research",
                arguments={"topic": topic_text.strip()},
            )

        # ------------------------------------------------------------
        # LIST CLIENTS
        # ------------------------------------------------------------
        if re.search(r"\b(?:list|show|display)\s+(?:all\s+)?clients?\b", lower):
            return Intent(tool_name="list_clients")

        # ------------------------------------------------------------
        # ADD CLIENT
        # ------------------------------------------------------------
        client_match = re.search(r"\badd\s+(?:client|prospect)\s+(.+)", lower)
        if client_match:
            name_text = clean[client_match.start(1):]
            return Intent(tool_name="add_client", arguments={"name": name_text.strip()})

        return Intent()


def create_default_intent_router() -> IntentRouter:
    return IntentRouter()


def run_tests() -> None:
    router = create_default_intent_router()

    tests = [
        (
            "time and date",
            "get_current_time",
            {},
        ),
        (
            "What time and date is it?",
            "get_current_time",
            {},
        ),
        (
            "What are my current system metrics?",
            "get_system_metrics",
            {},
        ),
        (
            "Give me today's vault summary",
            "get_daily_vault_summary",
            {},
        ),
        (
            "What is the current Master Brain vault summary?",
            "get_daily_vault_summary",
            {},
        ),
        (
            "Show me the vault summary",
            "get_daily_vault_summary",
            {},
        ),
        (
            "Search my vault for AgenticOS",
            "search_vault",
            {"query": "AgenticOS"},
        ),
        (
            "Search the vault for AgenticOS",
            "search_vault",
            {"query": "AgenticOS"},
        ),
        (
            "Find AgenticOS in my vault",
            "search_vault",
            {"query": "AgenticOS"},
        ),
        (
            "Read my Inbox note",
            "read_obsidian_note",
            {"filename": "Inbox"},
        ),
        (
            "Read Inbox",
            "read_obsidian_note",
            {"filename": "Inbox"},
        ),
        (
            "Show me Inbox.md",
            "read_obsidian_note",
            {"filename": "Inbox"},
        ),
        (
            "Open Notepad",
            "launch_app",
            {"target": "Notepad"},
        ),
        (
            "Arnie, open Notepad.",
            "launch_app",
            {"target": "Notepad"},
        ),
        (
            "Launch VS Code",
            "launch_app",
            {"target": "vscode"},
        ),
        (
            "Start Chrome",
            "launch_app",
            {"target": "chrome"},
        ),
        (
            "Search the web for the latest Ollama release",
            "web_search",
            {"query": "the latest Ollama release"},
        ),
        (
            "Search the internet for Ollama",
            "web_search",
            {"query": "Ollama"},
        ),
    ]

    for text, expected_tool, expected_args in tests:
        result = router.route(text)

        assert result.tool_name == expected_tool, (
            f"{text!r}: expected {expected_tool!r}, "
            f"got {result.tool_name!r}"
        )

        assert result.arguments == expected_args, (
            f"{text!r}: expected args {expected_args!r}, "
            f"got {result.arguments!r}"
        )

        print(
            f"✓ {text!r} → "
            f"{result.tool_name} {result.arguments}"
        )

    # Security boundary.
    result = router.route(
        "Search my vault for AgenticOS",
        is_owner=False,
    )

    assert result.tool_name is None
    assert result.arguments == {}

    print("✓ Non-owner tool routing blocked")
    print()
    print("INTENT ROUTER TESTS PASSED")


if __name__ == "__main__":
    run_tests()