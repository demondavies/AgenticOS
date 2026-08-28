"""
ARNIE Agentic OS
Local terminal capability.

Owns execution of approved local Windows terminal commands.
Authorization remains in core.policy / core.harness.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


AGENTICOS_ROOT = Path(r"G:\AgenticOS")

# Deliberately conservative legacy blocklist retained during migration.
DANGEROUS_KEYWORDS = (
    "del",
    "rmdir",
    "format",
    "rm -rf",
    "shutdown",
    "registry",
)


def run_terminal_command(command: str) -> str:
    """
    Execute a local Windows command.

    This capability does NOT decide whether the caller is authorized.
    PolicyEngine/Harness must perform authorization before invocation.
    """
    command = str(command or "").strip()

    print(
        f"⚡ [Agent Action] Executing system terminal command: {command}"
    )

    if any(keyword in command.lower() for keyword in DANGEROUS_KEYWORDS):
        return (
            "Security Violation: This terminal command is blocked by "
            "the Agentic OS Kernel Sandbox."
        )

    try:
        result = subprocess.run(
            command,
            shell=True,
            text=True,
            capture_output=True,
            timeout=10,
            cwd=str(AGENTICOS_ROOT),
        )

        output = result.stdout.strip() if result.stdout else ""
        errors = result.stderr.strip() if result.stderr else ""

        if not output and not errors:
            return (
                "Command executed successfully with zero console "
                "output text."
            )

        if errors:
            return (
                f"Windows Console Output:\n{output}\n\n"
                f"Console Error Log:\n{errors}"
            )

        return f"Windows Console Output:\n{output}"

    except subprocess.TimeoutExpired:
        return "Process Error: Command execution timed out."

    except Exception as exc:
        return f"Execution Failure: {exc}"


def run_tests() -> None:
    """Validate the terminal capability without executing a real command."""

    blocked = run_terminal_command("shutdown /s")
    assert blocked.startswith("Security Violation:")

    assert isinstance(DANGEROUS_KEYWORDS, tuple)
    assert AGENTICOS_ROOT == Path(r"G:\AgenticOS")

    print("✓ Terminal capability contract passed")


if __name__ == "__main__":
    run_tests()
