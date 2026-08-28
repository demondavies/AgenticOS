"""Regression tests for source-aware policy approval."""

from __future__ import annotations

from .agents import create_coordinator_agent
from .policy import PolicyDecision, PolicyEngine, PolicyRequest
from .tasks import Task


def _launch_app_request(source: str) -> PolicyRequest:
    return PolicyRequest(
        agent=create_coordinator_agent(),
        task=Task(
            title="Launch application",
            description="Launch Notepad.",
            workspace="system",
        ),
        tool=_launch_app_tool(),
        source=source,
    )


def _launch_app_tool():
    class _Status:
        value = "enabled"

    class _Risk:
        value = "privileged"

        def __eq__(self, other) -> bool:
            return getattr(other, "value", other) == self.value

    return type(
        "LaunchAppTool",
        (),
        {
            "name": "launch_app",
            "status": _Status(),
            "risk": _Risk(),
            "local_access": True,
            "mutates_state": True,
            "requires_approval": True,
        },
    )()


def test_web_ui_implicitly_approves_privileged_tool() -> None:
    result = PolicyEngine().evaluate(_launch_app_request("bot.intent"))

    assert result.decision == PolicyDecision.ALLOW
    assert result.tool_id == "launch_app"


def test_local_voice_implicitly_approves_privileged_tool() -> None:
    result = PolicyEngine().evaluate(
        _launch_app_request("bot.voice_intent")
    )

    assert result.decision == PolicyDecision.ALLOW


def test_discord_still_requires_human_approval() -> None:
    result = PolicyEngine().evaluate(_launch_app_request("discord"))

    assert result.decision == PolicyDecision.APPROVAL_REQUIRED


def test_trusted_source_does_not_override_a_deny() -> None:
    request = _launch_app_request("bot.intent")
    request.agent.remove_tool("launch_app")

    result = PolicyEngine().evaluate(request)

    assert result.decision == PolicyDecision.DENY


def run_tests() -> None:
    test_web_ui_implicitly_approves_privileged_tool()
    test_local_voice_implicitly_approves_privileged_tool()
    test_discord_still_requires_human_approval()
    test_trusted_source_does_not_override_a_deny()
    print("source-aware policy approval tests passed")


if __name__ == "__main__":
    run_tests()
