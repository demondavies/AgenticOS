"""Integration contract test for the managed privileged Tool boundary.

This test uses the real AgentHarness, real PolicyEngine, real ToolRegistry,
and real AgentRuntime. The final handler is synthetic, so no real privileged
system capability is executed.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

from .agent_runtime import AgentRuntime, ToolApprovalRequired
from .config import DEFAULT_MODEL
from .harness import AgentHarness
from .intent import create_default_intent_router
from .tasks import Task
from .tools import Tool, ToolRisk, create_default_registry


def test_privileged_tool_is_blocked_then_allowed() -> None:
    """Prove the Runtime -> Harness -> Policy -> Registry execution contract."""

    executions: list[Dict[str, Any]] = []

    def synthetic_privileged_handler(
        value: str = "",
    ) -> str:
        executions.append({"value": value})
        return f"synthetic:{value}"

    # Start from the real production registry so Harness construction can
    # bind its canonical launch_swarm and daily-summary handlers.
    registry = create_default_registry()

    tool = Tool(
        name="architecture_test_privileged",
        description="Synthetic privileged Tool used only by architecture tests.",
        handler=synthetic_privileged_handler,
        risk=ToolRisk.PRIVILEGED,
        local_access=True,
        mutates_state=True,
        requires_approval=True,
        deterministic=True,
        synthesis_required=False,
    )

    registry.register(tool)

    harness = AgentHarness(
        tool_registry=registry,
    )

    # The production Coordinator is the real Agent used by the Harness.
    task = Task(
        title="Architecture boundary test",
        description="Test the managed privileged execution boundary.",
        workspace="system",
    )

    agent = harness.select_agent(task)
    agent.allow_tool("architecture_test_privileged")

    runtime = AgentRuntime(
        harness=harness,
        tool_registry=registry,
        intent_router=create_default_intent_router(),
        base_system_prompt="",
        owner_extensions="",
        model=DEFAULT_MODEL,
    )

    async def exercise() -> None:
        # Unapproved privileged execution must stop before the handler.
        try:
            await runtime.execute_intent_tool(
                "architecture_test_privileged",
                {"value": "blocked"},
                source="discord",
            )
        except ToolApprovalRequired as error:
            assert error.tool_name == "architecture_test_privileged"
            assert error.arguments == {"value": "blocked"}
        else:
            raise AssertionError(
                "Unapproved privileged Tool execution must require approval."
            )

        assert executions == []

        # Explicit approval must permit the same Tool to execute.
        result = await runtime.execute_intent_tool(
            "architecture_test_privileged",
            {"value": "approved"},
            source="discord",
            user_approved=True,
        )

        assert result == "synthetic:approved"
        assert executions == [{"value": "approved"}]

    asyncio.run(exercise())


def run_tests() -> None:
    test_privileged_tool_is_blocked_then_allowed()

    print("=" * 72)
    print("ARNIE AGENTIC OS — EXECUTION BOUNDARY TEST")
    print("=" * 72)
    print()
    print("✓ Real AgentRuntime used")
    print("✓ Real AgentHarness used")
    print("✓ Real PolicyEngine used")
    print("✓ Real ToolRegistry used")
    print("✓ Real deterministic IntentRouter used")
    print("✓ Canonical DEFAULT_MODEL used")
    print("✓ Privileged execution blocked without approval")
    print("✓ Synthetic handler remained unexecuted while blocked")
    print("✓ Explicit approval permitted exactly one execution")
    print()
    print("EXECUTION BOUNDARY TEST PASSED")
    print("=" * 72)


if __name__ == "__main__":
    run_tests()