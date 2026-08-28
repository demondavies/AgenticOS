"""Architecture contract tests for the AgenticOS boundaries.

These tests intentionally inspect source structure rather than executing
application services. They act as lightweight architectural tripwires for
the ownership boundaries established during the AgenticOS migration.
"""

from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _python_files(relative_dir: str) -> list[Path]:
    directory = PROJECT_ROOT / relative_dir
    return sorted(directory.rglob("*.py"))


def _imports(source: str) -> list[str]:
    tree = ast.parse(source)
    imports: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)

    return imports


def test_core_and_capabilities_do_not_import_interfaces() -> None:
    """Core/capabilities must not depend upward on bot.py or api.py."""

    offenders: list[str] = []

    for relative_dir in ("core", "capabilities"):
        for path in _python_files(relative_dir):
            imports = _imports(_source(path))
            if any(
                module == "bot"
                or module.startswith("bot.")
                or module == "api"
                or module.startswith("api.")
                for module in imports
            ):
                offenders.append(str(path.relative_to(PROJECT_ROOT)))

    assert not offenders, (
        "Core/capabilities must not import interface modules: "
        + ", ".join(offenders)
    )


def test_tool_registry_has_no_legacy_bot_adapter() -> None:
    """The canonical Tool Registry must not retain the old bot adapter."""

    source = _source(PROJECT_ROOT / "core" / "tools.py")

    assert "_legacy_module" not in source
    assert "import bot" not in source
    assert "legacy_handler" not in source
    assert "legacy_adapter" not in source


def test_terminal_tool_uses_native_capability() -> None:
    """run_terminal_command must point at the canonical terminal capability."""

    source = _source(PROJECT_ROOT / "core" / "tools.py")

    assert (
        "from capabilities.system.terminal import run_terminal_command"
        in source
    )
    assert (
        "capabilities.system.terminal.run_terminal_command"
        in source
    )


def test_harness_uses_canonical_default_model() -> None:
    """Harness model fallbacks must come from core.config."""

    source = _source(PROJECT_ROOT / "core" / "harness.py")

    assert "from .config import DEFAULT_MODEL" in source
    assert '"hermes3:8b"' not in source
    assert "model: str = DEFAULT_MODEL" in source
    assert "or DEFAULT_MODEL" in source


def test_scheduler_owns_timing_not_business_logic() -> None:
    """Scheduler must receive execution callbacks rather than own capabilities."""

    path = PROJECT_ROOT / "core" / "scheduler.py"
    source = _source(path)
    imports = _imports(source)

    assert not any(
        module == "bot"
        or module.startswith("bot.")
        or module == "api"
        or module.startswith("api.")
        or module == "capabilities"
        or module.startswith("capabilities.")
        for module in imports
    )

    tree = ast.parse(source)

    function_names = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert "scheduled_vault_summary_job" in function_names
    assert "scheduled_memory_compaction_job" in function_names
    assert "init_scheduler" in function_names

    # The daily summary factory accepts the execution callback explicitly.
    summary_functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "scheduled_vault_summary_job"
    ]
    assert summary_functions

    arguments = summary_functions[0].args.kwonlyargs
    assert any(arg.arg == "execute_vault_summary" for arg in arguments)


def test_harness_binds_canonical_swarm_tool() -> None:
    """launch_swarm must be bound through the Harness Tool boundary."""

    source = _source(PROJECT_ROOT / "core" / "harness.py")

    assert '"launch_swarm"' in source
    assert "self.tools.bind_handler(" in source
    assert "self.execute_swarm" in source
    assert "SwarmManager(" in source


def test_harness_binds_daily_vault_summary_tool() -> None:
    """Daily vault summary must enter through the Harness-owned model boundary."""

    source = _source(PROJECT_ROOT / "core" / "harness.py")

    assert '"get_daily_vault_summary"' in source
    assert "self.tools.bind_handler(" in source
    assert "self.execute_daily_vault_summary" in source


def run_tests() -> None:
    tests = [
        test_core_and_capabilities_do_not_import_interfaces,
        test_tool_registry_has_no_legacy_bot_adapter,
        test_terminal_tool_uses_native_capability,
        test_harness_uses_canonical_default_model,
        test_scheduler_owns_timing_not_business_logic,
        test_harness_binds_canonical_swarm_tool,
        test_harness_binds_daily_vault_summary_tool,
    ]

    for test in tests:
        test()

    print("=" * 72)
    print("ARNIE AGENTIC OS — ARCHITECTURE CONTRACT TEST")
    print("=" * 72)
    print()
    for test in tests:
        print(f"✓ {test.__name__}")
    print()
    print("ARCHITECTURE CONTRACT TEST PASSED")
    print("=" * 72)


if __name__ == "__main__":
    run_tests()
