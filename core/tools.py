"""
ARNIE Agentic OS
Tool Domain Model

This module defines the provider-independent Tool contract.

IMPORTANT:
- A Tool is an action ARNIE can perform.
- Agents are granted access to Tools.
- The Harness will eventually enforce Tool permissions.
- The Tool itself does not decide whether an Agent is allowed to use it.

This file deliberately does not import:
    Ollama
    SQLite
    FastAPI
    Discord
    ChromaDB
    Kokoro
    existing ARNIE code

The actual existing tools will be migrated into this system later.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4


# ============================================================================
# HELPERS
# ============================================================================


def new_id(prefix: str) -> str:
    """Create a readable unique identifier."""
    return f"{prefix}_{uuid4().hex}"


# ============================================================================
# TOOL RISK
# ============================================================================


class ToolRisk(str, Enum):
    """
    Risk classification for a Tool.

    This is deliberately separate from permission.

    A tool may be:
        SAFE
        CONTROLLED
        PRIVILEGED

    The Harness will eventually use this classification when deciding
    whether an action requires additional checks or human approval.
    """

    SAFE = "safe"
    CONTROLLED = "controlled"
    PRIVILEGED = "privileged"


# ============================================================================
# TOOL STATUS
# ============================================================================


class ToolStatus(str, Enum):
    """
    Operational status of a Tool.
    """

    ENABLED = "enabled"
    DISABLED = "disabled"
    ERROR = "error"


# ============================================================================
# TOOL RESULT
# ============================================================================


@dataclass
class ToolResult:
    """
    Provider-independent result returned by a Tool.

    A Tool should never simply throw arbitrary data back into the Harness.

    It should return a structured result describing:
        success
        output
        error
        data
        metadata
    """

    success: bool

    output: Optional[str] = None

    data: Dict[str, Any] = field(default_factory=dict)

    error: Optional[str] = None

    metadata: Dict[str, Any] = field(default_factory=dict)

    # Optional execution information.
    tool_id: Optional[str] = None

    execution_id: Optional[str] = None


# ============================================================================
# TOOL DEFINITION
# ============================================================================


@dataclass
class Tool:
    """
    Definition of a capability available to ARNIE.

    A Tool describes WHAT an action does and HOW it may be invoked.

    The actual function is supplied separately through the `handler`.

    Example:

        Tool(
            name="get_current_time",
            description="Return the current local time.",
            risk=ToolRisk.SAFE,
            handler=get_current_time,
        )
    """

    name: str

    description: str

    handler: Callable[..., Any]

    id: str = field(default_factory=lambda: new_id("tool"))

    status: ToolStatus = ToolStatus.ENABLED

    risk: ToolRisk = ToolRisk.SAFE

    # Schema describing expected arguments.
    #
    # This intentionally uses a simple JSON-schema-like structure rather
    # than coupling ARNIE to a particular validation library.
    input_schema: Dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
        }
    )

    # Whether the tool can change external state.
    mutates_state: bool = False

    # Whether the tool can access the local machine.
    local_access: bool = False

    # Whether human approval should normally be required.
    requires_approval: bool = False

    # Human-readable category.
    category: str = "general"

    metadata: Dict[str, Any] = field(default_factory=dict)

    # ---------------------------------------------------------------------
    # Lifecycle
    # ---------------------------------------------------------------------

    def enable(self) -> None:
        """Enable the Tool."""
        self.status = ToolStatus.ENABLED

    def disable(self) -> None:
        """Disable the Tool."""
        self.status = ToolStatus.DISABLED

    def mark_error(self) -> None:
        """Mark the Tool as being in an error state."""
        self.status = ToolStatus.ERROR

    # ---------------------------------------------------------------------
    # Validation
    # ---------------------------------------------------------------------

    def validate_arguments(
        self,
        arguments: Dict[str, Any],
    ) -> None:
        """
        Perform basic argument validation.

        This is intentionally lightweight.

        A more sophisticated schema validator can be introduced later
        without changing the Tool abstraction.
        """

        if not isinstance(arguments, dict):
            raise TypeError(
                f"Tool '{self.name}' expects arguments as a dictionary."
            )

        schema = self.input_schema or {}

        required = schema.get("required", [])

        for field_name in required:
            if field_name not in arguments:
                raise ValueError(
                    f"Tool '{self.name}' requires argument "
                    f"'{field_name}'."
                )

        properties = schema.get("properties", {})

        for argument_name in arguments:
            if properties and argument_name not in properties:
                raise ValueError(
                    f"Tool '{self.name}' does not accept argument "
                    f"'{argument_name}'."
                )

    # ---------------------------------------------------------------------
    # Execution
    # ---------------------------------------------------------------------

    def execute(
        self,
        arguments: Optional[Dict[str, Any]] = None,
        execution_id: Optional[str] = None,
    ) -> ToolResult:
        """
        Execute the Tool handler.

        Permission checks belong to the Harness.

        The Tool is responsible for:
            - checking its own enabled state
            - validating arguments
            - calling its handler
            - normalizing the result
        """

        if self.status != ToolStatus.ENABLED:
            return ToolResult(
                success=False,
                error=(
                    f"Tool '{self.name}' is not enabled "
                    f"(status: {self.status.value})."
                ),
                tool_id=self.id,
                execution_id=execution_id,
            )

        arguments = arguments or {}

        try:
            self.validate_arguments(arguments)

            raw_result = self.handler(**arguments)

            # Already normalized.
            if isinstance(raw_result, ToolResult):
                if raw_result.tool_id is None:
                    raw_result.tool_id = self.id

                if raw_result.execution_id is None:
                    raw_result.execution_id = execution_id

                return raw_result

            # String result.
            if isinstance(raw_result, str):
                return ToolResult(
                    success=True,
                    output=raw_result,
                    tool_id=self.id,
                    execution_id=execution_id,
                )

            # Dictionary result.
            if isinstance(raw_result, dict):
                return ToolResult(
                    success=True,
                    data=raw_result,
                    tool_id=self.id,
                    execution_id=execution_id,
                )

            # Anything else.
            return ToolResult(
                success=True,
                output=str(raw_result),
                tool_id=self.id,
                execution_id=execution_id,
            )

        except Exception as exc:
            return ToolResult(
                success=False,
                error=str(exc),
                tool_id=self.id,
                execution_id=execution_id,
            )

    # ---------------------------------------------------------------------
    # Serialization
    # ---------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the Tool definition into a JSON-friendly dictionary.

        The actual Python handler is deliberately excluded.
        """

        data = asdict(self)

        data.pop("handler", None)

        data["status"] = self.status.value
        data["risk"] = self.risk.value

        return data


# ============================================================================
# TOOL REGISTRY
# ============================================================================


class ToolRegistry:
    """
    Registry containing Tools available to the Agentic OS.

    The Harness will eventually use this registry to discover and execute
    permitted capabilities.
    """

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(
        self,
        tool: Tool,
    ) -> None:
        """
        Register a Tool.
        """

        key = tool.name.strip().lower()

        if not key:
            raise ValueError("Tool name cannot be empty.")

        if key in self._tools:
            raise ValueError(
                f"Tool '{tool.name}' is already registered."
            )

        self._tools[key] = tool

    def get(
        self,
        tool_name: str,
    ) -> Tool:
        """
        Retrieve a Tool by name.
        """

        key = tool_name.strip().lower()

        if key not in self._tools:
            raise KeyError(
                f"Tool '{tool_name}' is not registered."
            )

        return self._tools[key]

    def remove(
        self,
        tool_name: str,
    ) -> None:
        """
        Remove a Tool from the registry.
        """

        key = tool_name.strip().lower()

        if key in self._tools:
            del self._tools[key]

    def list_tools(self) -> List[Tool]:
        """
        Return all registered Tools.
        """

        return list(self._tools.values())

    def list_enabled(self) -> List[Tool]:
        """
        Return all enabled Tools.
        """

        return [
            tool
            for tool in self._tools.values()
            if tool.status == ToolStatus.ENABLED
        ]

    def find_by_category(
        self,
        category: str,
    ) -> List[Tool]:
        """
        Find Tools belonging to a category.
        """

        target = category.strip().lower()

        return [
            tool
            for tool in self._tools.values()
            if tool.category.lower() == target
        ]


# ============================================================================
# TOOL PERMISSION POLICY
# ============================================================================


class ToolPermissionPolicy:
    """
    Central policy object for determining whether an Agent may use a Tool.

    IMPORTANT:

    This is only the first architectural layer.

    Later the policy can incorporate:
        - Agent identity
        - Task
        - Workspace
        - Tool risk
        - user approval
        - security policy
        - execution environment
    """

    def can_execute(
        self,
        agent: Any,
        tool: Tool,
    ) -> bool:
        """
        Determine whether the Agent is allowed to request this Tool.

        The Agent is intentionally typed loosely here to avoid creating
        a circular dependency between the domain modules.

        The Harness will eventually provide the richer policy context.
        """

        if tool.status != ToolStatus.ENABLED:
            return False

        # The Agent abstraction already exposes can_use_tool().
        if not agent.can_use_tool(tool.name):
            return False

        return True

    def requires_approval(
        self,
        agent: Any,
        tool: Tool,
    ) -> bool:
        """
        Determine whether a Tool requires human approval.
        """

        if tool.requires_approval:
            return True

        if tool.risk == ToolRisk.PRIVILEGED:
            return bool(
                agent.execution_policy.require_approval_for_privileged_tools
            )

        return False


# ============================================================================
# SAFE DEVELOPMENT TOOLS
# ============================================================================


def example_time_tool() -> str:
    """
    Tiny demonstration Tool.

    This is intentionally dependency-free.
    """

    from datetime import datetime

    return datetime.now().astimezone().isoformat()


def example_echo_tool(
    text: str,
) -> str:
    """
    Tiny demonstration Tool used by the test suite.
    """

    return text


def create_example_tools() -> ToolRegistry:
    """
    Create a tiny Tool registry for development/testing.

    These are NOT the production ARNIE tools.

    Existing bot.py tools will be migrated later.
    """

    registry = ToolRegistry()

    registry.register(
        Tool(
            name="get_current_time",
            description="Return the current local date and time.",
            handler=example_time_tool,
            risk=ToolRisk.SAFE,
            category="utility",
            input_schema={
                "type": "object",
                "properties": {},
            },
        )
    )

    registry.register(
        Tool(
            name="echo",
            description="Return the supplied text unchanged.",
            handler=example_echo_tool,
            risk=ToolRisk.SAFE,
            category="development",
            input_schema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                    }
                },
                "required": ["text"],
            },
        )
    )

    return registry


# ============================================================================
# DEVELOPMENT TESTS
# ============================================================================


def run_tests() -> None:
    """
    Dependency-free tests for the Tool domain model.

    These tests do NOT touch:
        - Ollama
        - SQLite
        - FastAPI
        - Discord
        - ChromaDB
        - existing ARNIE tools
    """

    print("=" * 60)
    print("ARNIE TOOL DOMAIN MODEL TEST")
    print("=" * 60)

    # ------------------------------------------------------------------
    # Test 1: Basic Tool creation
    # ------------------------------------------------------------------

    def hello_tool() -> str:
        return "Hello from ARNIE."

    tool = Tool(
        name="hello",
        description="Return a greeting.",
        handler=hello_tool,
    )

    assert tool.id.startswith("tool_")
    assert tool.status == ToolStatus.ENABLED
    assert tool.risk == ToolRisk.SAFE

    print("✓ Tool creation")

    # ------------------------------------------------------------------
    # Test 2: Tool execution
    # ------------------------------------------------------------------

    result = tool.execute()

    assert result.success is True
    assert result.output == "Hello from ARNIE."
    assert result.tool_id == tool.id

    print("✓ Tool execution")

    # ------------------------------------------------------------------
    # Test 3: Tool schema
    # ------------------------------------------------------------------

    echo_tool = Tool(
        name="echo",
        description="Echo text.",
        handler=example_echo_tool,
        input_schema={
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                }
            },
            "required": ["text"],
        },
    )

    result = echo_tool.execute(
        {
            "text": "ARNIE is alive.",
        }
    )

    assert result.success is True
    assert result.output == "ARNIE is alive."

    print("✓ Argument validation and execution")

    # ------------------------------------------------------------------
    # Test 4: Missing required argument
    # ------------------------------------------------------------------

    result = echo_tool.execute()

    assert result.success is False
    assert result.error is not None
    assert "text" in result.error

    print("✓ Required argument protection")

    # ------------------------------------------------------------------
    # Test 5: Unknown argument
    # ------------------------------------------------------------------

    result = echo_tool.execute(
        {
            "text": "hello",
            "unexpected": "bad",
        }
    )

    assert result.success is False
    assert result.error is not None

    print("✓ Unknown argument protection")

    # ------------------------------------------------------------------
    # Test 6: Disabled Tool
    # ------------------------------------------------------------------

    tool.disable()

    result = tool.execute()

    assert result.success is False
    assert tool.status == ToolStatus.DISABLED

    tool.enable()

    assert tool.status == ToolStatus.ENABLED

    print("✓ Tool enable/disable")

    # ------------------------------------------------------------------
    # Test 7: Registry
    # ------------------------------------------------------------------

    registry = ToolRegistry()

    registry.register(tool)

    found = registry.get("hello")

    assert found is tool

    print("✓ Tool registry")

    # ------------------------------------------------------------------
    # Test 8: Duplicate protection
    # ------------------------------------------------------------------

    duplicate_failed = False

    try:
        registry.register(tool)
    except ValueError:
        duplicate_failed = True

    assert duplicate_failed is True

    print("✓ Duplicate Tool protection")

    # ------------------------------------------------------------------
    # Test 9: Risk classification
    # ------------------------------------------------------------------

    privileged_tool = Tool(
        name="privileged_test",
        description="Test privileged action.",
        handler=lambda: "privileged",
        risk=ToolRisk.PRIVILEGED,
        requires_approval=True,
        mutates_state=True,
        local_access=True,
    )

    assert privileged_tool.risk == ToolRisk.PRIVILEGED
    assert privileged_tool.requires_approval is True
    assert privileged_tool.mutates_state is True
    assert privileged_tool.local_access is True

    print("✓ Tool risk classification")

    # ------------------------------------------------------------------
    # Test 10: Example registry
    # ------------------------------------------------------------------

    example_registry = create_example_tools()

    assert len(example_registry.list_tools()) == 2

    assert (
        example_registry.get("get_current_time")
        is not None
    )

    assert (
        example_registry.get("echo")
        is not None
    )

    print("✓ Example Tool registry")

    # ------------------------------------------------------------------
    # Test 11: Permission policy
    # ------------------------------------------------------------------

    # Lightweight fake Agent for this domain-level test.
    class FakePolicy:
        require_approval_for_privileged_tools = True

    class FakeAgent:
        execution_policy = FakePolicy()

        def can_use_tool(self, name: str) -> bool:
            return name == "hello"

    policy = ToolPermissionPolicy()

    safe_tool = registry.get("hello")

    assert policy.can_execute(
        FakeAgent(),
        safe_tool,
    ) is True

    assert policy.requires_approval(
        FakeAgent(),
        safe_tool,
    ) is False

    assert policy.can_execute(
        FakeAgent(),
        privileged_tool,
    ) is False

    print("✓ Tool permission policy")

    # ------------------------------------------------------------------
    # Test 12: Serialization
    # ------------------------------------------------------------------

    data = privileged_tool.to_dict()

    assert isinstance(data, dict)
    assert data["name"] == "privileged_test"
    assert data["risk"] == "privileged"

    # Handler must never appear in serialized Tool definitions.
    assert "handler" not in data

    print("✓ Tool serialization")

    print()
    print("=" * 60)
    print("TOOL DOMAIN MODEL TEST PASSED")
    print("=" * 60)


if __name__ == "__main__":
    run_tests()