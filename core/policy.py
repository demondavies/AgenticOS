"""
ARNIE Agentic OS
Policy Domain Model

The Policy Engine is the security decision layer between an Agent and a Tool.

The model may REQUEST an action.

The model does NOT receive execution authority.

The Policy Engine evaluates:

    WHO?
        Agent

    WHAT?
        Tool

    WHY?
        Task

    WHERE?
        Workspace

    HOW RISKY?
        ToolRisk

The result is one of:

    ALLOW
    APPROVAL_REQUIRED
    DENY

This module is intentionally provider-independent and execution-independent.

It does NOT:
    - execute tools
    - call Ollama
    - access the filesystem
    - access SQLite
    - access Discord
    - access FastAPI

The Harness will eventually call this policy layer before any Tool execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .agents import Agent
from .tasks import Task
from .tools import Tool, ToolRisk


# Sources set by trusted local interface adapters. These satisfy approval
# prompts, but only after all DENY checks have passed.
AUTO_APPROVED_SOURCES = frozenset(
    {
        "ui",
        "voice",
        "bot.intent",
        "bot.voice_intent",
    }
)


# ============================================================================
# POLICY DECISION
# ============================================================================


class PolicyDecision(str, Enum):
    """
    Final decision produced by the Policy Engine.
    """

    ALLOW = "allow"
    APPROVAL_REQUIRED = "approval_required"
    DENY = "deny"


# ============================================================================
# DENIAL REASONS
# ============================================================================


class PolicyReason(str, Enum):
    """
    Standard reasons for a policy decision.

    Keeping these structured means the UI, logs and Harness do not have to
    parse arbitrary human-readable error strings.
    """

    ALLOWED = "allowed"

    AGENT_NOT_PERMITTED = "agent_not_permitted"

    TOOL_DISABLED = "tool_disabled"

    PRIVILEGED_TOOL = "privileged_tool"

    APPROVAL_REQUIRED = "approval_required"

    LOCAL_ACCESS_DENIED = "local_access_denied"

    STATE_MUTATION_DENIED = "state_mutation_denied"

    WORKSPACE_RESTRICTED = "workspace_restricted"

    TOOL_NOT_FOUND = "tool_not_found"

    INVALID_REQUEST = "invalid_request"


# ============================================================================
# POLICY REQUEST
# ============================================================================


@dataclass(frozen=True)
class PolicyRequest:
    """
    Complete context for a policy decision.

    This is deliberately explicit.

    We do not want the security layer relying on hidden global state.
    """

    agent: Agent

    task: Task

    tool: Tool

    # Optional indication that the user explicitly approved this action.
    user_approved: bool = False

    # Source/interface information supplied by the Harness boundary.
    source: str = "harness"

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )


# ============================================================================
# POLICY RESULT
# ============================================================================


@dataclass(frozen=True)
class PolicyResult:
    """
    Structured result of a policy evaluation.
    """

    decision: PolicyDecision

    reason: PolicyReason

    message: str

    agent_id: str

    task_id: str

    tool_id: str

    tool_name: str

    risk: ToolRisk

    requires_approval: bool = False

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    @property
    def allowed(self) -> bool:
        """
        Convenience property.

        True only when execution may proceed immediately.
        """

        return self.decision == PolicyDecision.ALLOW

    @property
    def denied(self) -> bool:
        """
        True when execution is explicitly forbidden.
        """

        return self.decision == PolicyDecision.DENY

    @property
    def approval_required(self) -> bool:
        """
        True when human approval must happen before execution.
        """

        return (
            self.decision
            == PolicyDecision.APPROVAL_REQUIRED
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the result into a JSON-friendly dictionary.
        """

        return {
            "decision": self.decision.value,
            "reason": self.reason.value,
            "message": self.message,
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "tool_id": self.tool_id,
            "tool_name": self.tool_name,
            "risk": self.risk.value,
            "requires_approval": self.requires_approval,
            "metadata": self.metadata,
        }


# ============================================================================
# WORKSPACE POLICY
# ============================================================================


@dataclass
class WorkspacePolicy:
    """
    Security policy for a workspace.

    A workspace represents an operational boundary.

    Examples:

        personal
        agency
        media
        development
        system

    The initial rules are intentionally conservative.
    """

    name: str

    # Whether tools with local machine access may execute.
    allow_local_access: bool = True

    # Whether tools that mutate external/local state may execute.
    allow_state_mutation: bool = True

    # Whether privileged tools may ever execute.
    allow_privileged_tools: bool = False

    # Tools that are explicitly denied regardless of Agent permission.
    denied_tools: List[str] = field(
        default_factory=list
    )

    # Tools that require approval in this workspace.
    approval_tools: List[str] = field(
        default_factory=list
    )

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    def denies_tool(
        self,
        tool_name: str,
    ) -> bool:
        """
        Return True when the workspace explicitly denies a Tool.
        """

        return tool_name.lower() in {
            item.lower()
            for item in self.denied_tools
        }

    def requires_tool_approval(
        self,
        tool_name: str,
    ) -> bool:
        """
        Return True when the workspace requires approval for a Tool.
        """

        return tool_name.lower() in {
            item.lower()
            for item in self.approval_tools
        }


# ============================================================================
# POLICY ENGINE
# ============================================================================


class PolicyEngine:
    """
    Central security decision engine.

    Evaluation order is deliberately conservative:

        1. Validate request
        2. Tool enabled?
        3. Agent permitted?
        4. Workspace restrictions
        5. Local-access restrictions
        6. State-mutation restrictions
        7. Privileged-tool restrictions
        8. Tool approval requirements
        9. Workspace approval requirements
        10. Explicit user approval or trusted local source
        11. ALLOW

    The engine NEVER executes the Tool.
    """

    def __init__(
        self,
        workspace_policies: Optional[
            Dict[str, WorkspacePolicy]
        ] = None,
    ) -> None:

        self._workspace_policies = (
            workspace_policies
            if workspace_policies is not None
            else self._default_workspace_policies()
        )

    # ---------------------------------------------------------------------
    # Main evaluation
    # ---------------------------------------------------------------------

    def evaluate(
        self,
        request: PolicyRequest,
    ) -> PolicyResult:
        """
        Evaluate a Tool execution request.
        """

        # ==============================================================
        # 1. Validate
        # ==============================================================

        if request.agent is None:
            return self._deny(
                request,
                PolicyReason.INVALID_REQUEST,
                "No Agent was supplied.",
            )

        if request.task is None:
            return self._deny(
                request,
                PolicyReason.INVALID_REQUEST,
                "No Task was supplied.",
            )

        if request.tool is None:
            return self._deny(
                request,
                PolicyReason.INVALID_REQUEST,
                "No Tool was supplied.",
            )

        # ==============================================================
        # 2. Tool enabled?
        # ==============================================================

        if request.tool.status.value != "enabled":
            return self._deny(
                request,
                PolicyReason.TOOL_DISABLED,
                f"Tool '{request.tool.name}' is not enabled.",
            )

        # ==============================================================
        # 3. Agent permitted?
        # ==============================================================

        if not request.agent.can_use_tool(
            request.tool.name
        ):
            return self._deny(
                request,
                PolicyReason.AGENT_NOT_PERMITTED,
                (
                    f"Agent '{request.agent.name}' is not "
                    f"permitted to use Tool "
                    f"'{request.tool.name}'."
                ),
            )

        # ==============================================================
        # 4. Workspace
        # ==============================================================

        workspace = request.task.workspace

        workspace_policy = (
            self._workspace_policies.get(workspace)
        )

        if workspace_policy is None:
            return self._deny(
                request,
                PolicyReason.WORKSPACE_RESTRICTED,
                (
                    f"No policy exists for workspace "
                    f"'{workspace}'."
                ),
            )

        if workspace_policy.denies_tool(
            request.tool.name
        ):
            return self._deny(
                request,
                PolicyReason.WORKSPACE_RESTRICTED,
                (
                    f"Tool '{request.tool.name}' is denied "
                    f"in workspace '{workspace}'."
                ),
            )

        # ==============================================================
        # 5. Local access
        # ==============================================================

        if (
            request.tool.local_access
            and not workspace_policy.allow_local_access
        ):
            return self._deny(
                request,
                PolicyReason.LOCAL_ACCESS_DENIED,
                (
                    f"Local-access Tool '{request.tool.name}' "
                    f"is not permitted in workspace "
                    f"'{workspace}'."
                ),
            )

        # ==============================================================
        # 6. State mutation
        # ==============================================================

        if (
            request.tool.mutates_state
            and not workspace_policy.allow_state_mutation
        ):
            return self._deny(
                request,
                PolicyReason.STATE_MUTATION_DENIED,
                (
                    f"State-mutating Tool '{request.tool.name}' "
                    f"is not permitted in workspace "
                    f"'{workspace}'."
                ),
            )

        # ==============================================================
        # 7. Privileged tool
        # ==============================================================

        if request.tool.risk == ToolRisk.PRIVILEGED:

            if not workspace_policy.allow_privileged_tools:
                return self._deny(
                    request,
                    PolicyReason.PRIVILEGED_TOOL,
                    (
                        f"Privileged Tool '{request.tool.name}' "
                        f"is not permitted in workspace "
                        f"'{workspace}'."
                    ),
                )

        # ==============================================================
        # 8. Tool-level approval
        # ==============================================================

        tool_requires_approval = (
            request.tool.requires_approval
        )

        # ==============================================================
        # 9. Workspace approval
        # ==============================================================

        workspace_requires_approval = (
            workspace_policy.requires_tool_approval(
                request.tool.name
            )
        )

        # ==============================================================
        # 10. Approval
        # ==============================================================

        requires_approval = (
            tool_requires_approval
            or workspace_requires_approval
            or (
                request.tool.risk
                == ToolRisk.PRIVILEGED
                and request.agent.execution_policy
                .require_approval_for_privileged_tools
            )
        )

        source_auto_approved = (
            self.source_is_auto_approved(request.source)
        )

        approval_satisfied = (
            request.user_approved
            or source_auto_approved
        )

        if requires_approval:

            if not approval_satisfied:
                return self._approval_required(
                    request,
                    (
                        f"Tool '{request.tool.name}' requires "
                        f"human approval before execution."
                    ),
                )

        # ==============================================================
        # 11. ALLOW
        # ==============================================================

        return PolicyResult(
            decision=PolicyDecision.ALLOW,
            reason=PolicyReason.ALLOWED,
            message=(
                f"Tool '{request.tool.name}' is permitted "
                f"for Agent '{request.agent.name}'."
            ),
            agent_id=request.agent.id,
            task_id=request.task.id,
            tool_id=request.tool.name,
            tool_name=request.tool.name,
            risk=request.tool.risk,
            requires_approval=False,
            metadata={
                "workspace": workspace,
                "source": request.source,
                "source_auto_approved": source_auto_approved,
                "approval_satisfied_by": (
                    "explicit_user"
                    if request.user_approved
                    else (
                        "trusted_source"
                        if source_auto_approved
                        else None
                    )
                ),
            },
        )

    # ---------------------------------------------------------------------
    # Convenience
    # ---------------------------------------------------------------------

    def can_execute(
        self,
        request: PolicyRequest,
    ) -> bool:
        """
        Return True only if the request can execute immediately.
        """

        return self.evaluate(request).allowed

    @staticmethod
    def source_is_auto_approved(
        source: str,
    ) -> bool:
        """
        Return True when the request came from a trusted local interface.
        """

        if not isinstance(source, str):
            return False

        return source.strip().lower() in AUTO_APPROVED_SOURCES

    # ---------------------------------------------------------------------
    # Workspace management
    # ---------------------------------------------------------------------

    def register_workspace(
        self,
        policy: WorkspacePolicy,
    ) -> None:
        """
        Register or replace a workspace policy.
        """

        if not policy.name.strip():
            raise ValueError(
                "Workspace policy name cannot be empty."
            )

        self._workspace_policies[
            policy.name
        ] = policy

    def get_workspace_policy(
        self,
        workspace: str,
    ) -> WorkspacePolicy:
        """
        Retrieve a workspace policy.
        """

        if workspace not in self._workspace_policies:
            raise KeyError(
                f"No policy exists for workspace '{workspace}'."
            )

        return self._workspace_policies[workspace]

    # ---------------------------------------------------------------------
    # Internal result helpers
    # ---------------------------------------------------------------------

    @staticmethod
    def _deny(
        request: PolicyRequest,
        reason: PolicyReason,
        message: str,
    ) -> PolicyResult:
        """
        Create a DENY result.
        """

        return PolicyResult(
            decision=PolicyDecision.DENY,
            reason=reason,
            message=message,
            agent_id=request.agent.id,
            task_id=request.task.id,
            tool_id=request.tool.name,
            tool_name=request.tool.name,
            risk=request.tool.risk,
            requires_approval=False,
        )

    @staticmethod
    def _approval_required(
        request: PolicyRequest,
        message: str,
    ) -> PolicyResult:
        """
        Create an APPROVAL_REQUIRED result.
        """

        return PolicyResult(
            decision=PolicyDecision.APPROVAL_REQUIRED,
            reason=PolicyReason.APPROVAL_REQUIRED,
            message=message,
            agent_id=request.agent.id,
            task_id=request.task.id,
            tool_id=request.tool.name,
            tool_name=request.tool.name,
            risk=request.tool.risk,
            requires_approval=True,
        )

    # ---------------------------------------------------------------------
    # Defaults
    # ---------------------------------------------------------------------

    @staticmethod
    def _default_workspace_policies(
    ) -> Dict[str, WorkspacePolicy]:
        """
        Conservative default workspace policies.
        """

        return {
            # ----------------------------------------------------------
            # Personal
            # ----------------------------------------------------------

            "personal": WorkspacePolicy(
                name="personal",
                allow_local_access=True,
                allow_state_mutation=True,
                allow_privileged_tools=False,
            ),

            # ----------------------------------------------------------
            # Agency
            # ----------------------------------------------------------

            "agency": WorkspacePolicy(
                name="agency",
                allow_local_access=True,
                allow_state_mutation=True,
                allow_privileged_tools=False,
            ),

            # ----------------------------------------------------------
            # Media
            # ----------------------------------------------------------

            "media": WorkspacePolicy(
                name="media",
                allow_local_access=True,
                allow_state_mutation=True,
                allow_privileged_tools=False,
            ),

            # ----------------------------------------------------------
            # Development
            # ----------------------------------------------------------

            "development": WorkspacePolicy(
                name="development",
                allow_local_access=True,
                allow_state_mutation=True,
                allow_privileged_tools=False,
            ),

            # ----------------------------------------------------------
            # System
            #
            # This is intentionally locked down.
            # Privileged Tools still require explicit approval.
            # ----------------------------------------------------------

            "system": WorkspacePolicy(
                name="system",
                allow_local_access=True,
                allow_state_mutation=True,
                allow_privileged_tools=True,
            ),

            # ----------------------------------------------------------
            # Client
            #
            # Owner-initiated actions are auto-approved via trusted local
            # sources (see AUTO_APPROVED_SOURCES). Status changes require
            # explicit approval. Non-owner requests never reach the Policy
            # layer at all — they are denied upstream by intent routing.
            # ----------------------------------------------------------

            "client": WorkspacePolicy(
                name="client",
                allow_local_access=True,
                allow_state_mutation=True,
                allow_privileged_tools=False,
                approval_tools=["update_client_status"],
            ),

            # ----------------------------------------------------------
            # Prospects (Phase 24 — Lead Research Engine)
            # ----------------------------------------------------------

            "prospects": WorkspacePolicy(
                name="prospects",
                allow_local_access=True,
                allow_state_mutation=True,
                allow_privileged_tools=False,
            ),

            # ----------------------------------------------------------
            # Outreach (Phase 25 — Outreach Drafting Engine)
            # ----------------------------------------------------------

            "outreach": WorkspacePolicy(
                name="outreach",
                allow_local_access=True,
                allow_state_mutation=True,
                allow_privileged_tools=False,
            ),
        }


# ============================================================================
# DEVELOPMENT TESTS
# ============================================================================


def run_tests() -> None:
    """
    Dependency-free tests for the Policy Engine.

    These tests do NOT execute any real Tool.
    """

    print("=" * 60)
    print("ARNIE POLICY ENGINE TEST")
    print("=" * 60)

    # ------------------------------------------------------------------
    # Imports needed for test objects
    # ------------------------------------------------------------------

    from .agents import Agent
    from .tasks import Task
    from .tools import Tool, ToolRisk, ToolStatus

    # ------------------------------------------------------------------
    # Test Agent
    # ------------------------------------------------------------------

    agent = Agent(
        name="Test Agent",
        role="Security test agent",
        system_prompt="You are a test agent.",
    )

    # ------------------------------------------------------------------
    # Safe Tool
    # ------------------------------------------------------------------

    safe_tool = Tool(
        name="safe_test",
        description="A harmless test tool.",
        handler=lambda: "safe",
        risk=ToolRisk.SAFE,
    )

    agent.allow_tool("safe_test")

    # ------------------------------------------------------------------
    # Task
    # ------------------------------------------------------------------

    task = Task(
        title="Policy test",
        description="Test policy decisions.",
        workspace="development",
    )

    # ------------------------------------------------------------------
    # Engine
    # ------------------------------------------------------------------

    policy = PolicyEngine()

    # ------------------------------------------------------------------
    # Test 1: Safe allowed Tool
    # ------------------------------------------------------------------

    result = policy.evaluate(
        PolicyRequest(
            agent=agent,
            task=task,
            tool=safe_tool,
        )
    )

    assert result.decision == PolicyDecision.ALLOW
    assert result.allowed is True
    assert result.denied is False
    assert result.approval_required is False

    print("✓ Safe Tool allowed")

    # ------------------------------------------------------------------
    # Test 2: Agent without permission
    # ------------------------------------------------------------------

    forbidden_tool = Tool(
        name="forbidden_test",
        description="A Tool the Agent cannot use.",
        handler=lambda: "forbidden",
        risk=ToolRisk.SAFE,
    )

    result = policy.evaluate(
        PolicyRequest(
            agent=agent,
            task=task,
            tool=forbidden_tool,
        )
    )

    assert result.decision == PolicyDecision.DENY
    assert result.reason == PolicyReason.AGENT_NOT_PERMITTED

    print("✓ Unpermitted Agent denied")

    # ------------------------------------------------------------------
    # Test 3: Disabled Tool
    # ------------------------------------------------------------------

    disabled_tool = Tool(
        name="disabled_test",
        description="Disabled Tool.",
        handler=lambda: "disabled",
        risk=ToolRisk.SAFE,
    )

    disabled_tool.disable()

    agent.allow_tool("disabled_test")

    result = policy.evaluate(
        PolicyRequest(
            agent=agent,
            task=task,
            tool=disabled_tool,
        )
    )

    assert result.decision == PolicyDecision.DENY
    assert result.reason == PolicyReason.TOOL_DISABLED

    print("✓ Disabled Tool denied")

    # ------------------------------------------------------------------
    # Test 4: Approval-required Tool
    # ------------------------------------------------------------------

    approval_tool = Tool(
        name="approval_test",
        description="Requires human approval.",
        handler=lambda: "approved",
        risk=ToolRisk.CONTROLLED,
        requires_approval=True,
    )

    agent.allow_tool("approval_test")

    result = policy.evaluate(
        PolicyRequest(
            agent=agent,
            task=task,
            tool=approval_tool,
        )
    )

    assert (
        result.decision
        == PolicyDecision.APPROVAL_REQUIRED
    )

    assert result.approval_required is True

    print("✓ Approval requirement enforced")

    # ------------------------------------------------------------------
    # Test 5: Explicit approval
    # ------------------------------------------------------------------

    result = policy.evaluate(
        PolicyRequest(
            agent=agent,
            task=task,
            tool=approval_tool,
            user_approved=True,
        )
    )

    assert result.decision == PolicyDecision.ALLOW

    print("✓ Explicit approval permits Tool")

    # ------------------------------------------------------------------
    # Test 6: Privileged Tool
    # ------------------------------------------------------------------

    privileged_tool = Tool(
        name="privileged_test",
        description="Privileged operation.",
        handler=lambda: "privileged",
        risk=ToolRisk.PRIVILEGED,
        local_access=True,
        mutates_state=True,
    )

    agent.allow_tool("privileged_test")

    result = policy.evaluate(
        PolicyRequest(
            agent=agent,
            task=task,
            tool=privileged_tool,
        )
    )

    assert result.decision == PolicyDecision.DENY
    assert result.reason == PolicyReason.PRIVILEGED_TOOL

    print("✓ Privileged Tool denied by workspace")

    # ------------------------------------------------------------------
    # Test 7: System workspace
    # ------------------------------------------------------------------

    system_task = Task(
        title="System policy test",
        description="Test system workspace.",
        workspace="system",
    )

    result = policy.evaluate(
        PolicyRequest(
            agent=agent,
            task=system_task,
            tool=privileged_tool,
            user_approved=False,
        )
    )

    assert (
        result.decision
        == PolicyDecision.APPROVAL_REQUIRED
    )

    print("✓ System workspace requires approval")

    # ------------------------------------------------------------------
    # Test 8: System workspace with approval
    # ------------------------------------------------------------------

    result = policy.evaluate(
        PolicyRequest(
            agent=agent,
            task=system_task,
            tool=privileged_tool,
            user_approved=True,
        )
    )

    assert result.decision == PolicyDecision.ALLOW

    print("✓ Approved privileged System action allowed")

    # ------------------------------------------------------------------
    # Test 9: Workspace denial
    # ------------------------------------------------------------------

    restricted_policy = WorkspacePolicy(
        name="restricted",
        allow_local_access=False,
        allow_state_mutation=False,
        allow_privileged_tools=False,
    )

    policy.register_workspace(
        restricted_policy
    )

    restricted_task = Task(
        title="Restricted test",
        description="Test restricted workspace.",
        workspace="restricted",
    )

    local_tool = Tool(
        name="local_test",
        description="Uses local machine access.",
        handler=lambda: "local",
        risk=ToolRisk.CONTROLLED,
        local_access=True,
    )

    agent.allow_tool("local_test")

    result = policy.evaluate(
        PolicyRequest(
            agent=agent,
            task=restricted_task,
            tool=local_tool,
        )
    )

    assert result.decision == PolicyDecision.DENY
    assert (
        result.reason
        == PolicyReason.LOCAL_ACCESS_DENIED
    )

    print("✓ Restricted local access denied")

    # ------------------------------------------------------------------
    # Test 10: State mutation denial
    # ------------------------------------------------------------------

    mutation_tool = Tool(
        name="mutation_test",
        description="Changes state.",
        handler=lambda: "mutation",
        risk=ToolRisk.CONTROLLED,
        mutates_state=True,
    )

    agent.allow_tool("mutation_test")

    result = policy.evaluate(
        PolicyRequest(
            agent=agent,
            task=restricted_task,
            tool=mutation_tool,
        )
    )

    assert result.decision == PolicyDecision.DENY
    assert (
        result.reason
        == PolicyReason.STATE_MUTATION_DENIED
    )

    print("✓ State mutation denied")

    # ------------------------------------------------------------------
    # Test 11: Unknown workspace
    # ------------------------------------------------------------------

    unknown_task = Task(
        title="Unknown workspace",
        description="Test unknown workspace.",
        workspace="unknown_workspace",
    )

    result = policy.evaluate(
        PolicyRequest(
            agent=agent,
            task=unknown_task,
            tool=safe_tool,
        )
    )

    assert result.decision == PolicyDecision.DENY
    assert (
        result.reason
        == PolicyReason.WORKSPACE_RESTRICTED
    )

    print("✓ Unknown workspace denied")

    # ------------------------------------------------------------------
    # Test 12: Serialization
    # ------------------------------------------------------------------

    serialized = result.to_dict()

    assert isinstance(serialized, dict)
    assert serialized["decision"] == "deny"
    assert serialized["reason"] == "workspace_restricted"

    print("✓ Policy result serialization")

    print()
    print("=" * 60)
    print("POLICY ENGINE TEST PASSED")
    print("=" * 60)


if __name__ == "__main__":
    run_tests()
