"""Regression tests for the extracted AgenticOS runtime boundary."""

from __future__ import annotations

import asyncio

from .agent_runtime import AgentRuntime, ToolApprovalRequired


class _Risk:
    PRIVILEGED = "privileged"


class _Tool:
    risk = _Risk.PRIVILEGED


class _Registry:
    def require(self, name):
        assert name == "launch_swarm"
        return _Tool()


class _Harness:
    def __init__(self):
        self.authorization = []
        self.executions = []

    def select_agent(self, task):
        return "coordinator"

    def _authorize_tool(self, tool_name, *, task, agent, source, user_approved):
        self.authorization.append((tool_name, task.workspace, agent, source, user_approved))
        return type("Decision", (), {"approval_required": not user_approved, "message": "Approval required"})()

    async def execute_tool_async(self, tool_name, arguments, *, task, agent, source, user_approved):
        self.executions.append((tool_name, arguments, task.workspace, agent, source, user_approved))
        return "launched"


def test_runtime_executes_tools_through_harness_after_approval():
    harness = _Harness()
    runtime = AgentRuntime(
        harness=harness,
        tool_registry=_Registry(),
        intent_router=None,
        model_chat=None,
        metrics_provider=None,
        base_system_prompt="",
        owner_extensions="",
        privileged_risk=_Risk.PRIVILEGED,
    )

    try:
        asyncio.run(runtime.execute_tool("launch_swarm", {"mission": "test"}, source="discord"))
    except ToolApprovalRequired as error:
        assert error.tool_name == "launch_swarm"
        assert error.arguments == {"mission": "test"}
    else:
        raise AssertionError("An unapproved privileged tool must request approval")

    result = asyncio.run(
        runtime.execute_tool(
            "launch_swarm",
            {"mission": "test"},
            source="discord",
            user_approved=True,
        )
    )

    assert result == "launched"
    assert harness.authorization == [
        ("launch_swarm", "system", "coordinator", "discord", False),
        ("launch_swarm", "system", "coordinator", "discord", True),
    ]
    assert harness.executions == [
        ("launch_swarm", {"mission": "test"}, "system", "coordinator", "discord", True)
    ]
