"""
AgenticOS Tool Registry

Canonical boundary between the AgenticOS harness/policy layer and executable tools.

Design goals:
- Explicit tool registration
- No LLM-facing execution logic
- No giant if/elif dispatcher
- Tools expose stable names and descriptions
- Execution is centralized through ToolRegistry
- Policy remains a separate concern
- Existing legacy bot.py can migrate onto this boundary incrementally
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


ToolHandler = Callable[..., Any]


@dataclass(frozen=True)
class ToolDefinition:
    """
    Immutable definition of an AgenticOS tool.
    """

    name: str
    description: str
    handler: ToolHandler


class ToolRegistry:
    """
    Central registry for executable AgenticOS tools.

    The registry knows:
        - what tools exist
        - how they are described
        - how to invoke them

    The registry does NOT decide:
        - whether a caller is allowed to use a tool
        - whether a tool requires approval
        - whether execution is safe

    Those decisions belong to the PolicyEngine / Harness layer.
    """

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str,
        description: str,
        handler: ToolHandler,
    ) -> ToolDefinition:
        """
        Register a tool.

        Duplicate tool names are rejected deliberately.
        Silent replacement would make the execution surface
        difficult to reason about.
        """

        normalized_name = name.strip()

        if not normalized_name:
            raise ValueError("Tool name cannot be empty.")

        if normalized_name in self._tools:
            raise ValueError(
                f"Tool already registered: {normalized_name}"
            )

        definition = ToolDefinition(
            name=normalized_name,
            description=description.strip(),
            handler=handler,
        )

        self._tools[normalized_name] = definition

        return definition

    def unregister(self, name: str) -> None:
        """
        Remove a registered tool.

        Primarily useful for tests and controlled runtime configuration.
        """

        self._tools.pop(name, None)

    def get(self, name: str) -> ToolDefinition | None:
        """
        Retrieve a tool definition by name.
        """

        return self._tools.get(name)

    def require(self, name: str) -> ToolDefinition:
        """
        Retrieve a tool definition or raise a clear error.
        """

        tool = self.get(name)

        if tool is None:
            raise KeyError(f"Unknown tool: {name}")

        return tool

    def has(self, name: str) -> bool:
        """
        Return True if the tool is registered.
        """

        return name in self._tools

    def list(self) -> list[ToolDefinition]:
        """
        Return all registered tools in deterministic name order.
        """

        return [
            self._tools[name]
            for name in sorted(self._tools)
        ]

    def names(self) -> list[str]:
        """
        Return registered tool names in deterministic order.
        """

        return sorted(self._tools)

    def describe(self) -> list[dict[str, str]]:
        """
        Return an LLM/UI-friendly description of the available tools.

        Handlers themselves are intentionally excluded.
        """

        return [
            {
                "name": tool.name,
                "description": tool.description,
            }
            for tool in self.list()
        ]

    def execute(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        """
        Execute a registered tool.

        IMPORTANT:
        This is the execution boundary, not the authorization boundary.

        Callers should pass through the Harness / PolicyEngine before
        reaching this method.
        """

        tool = self.require(name)

        if arguments is None:
            arguments = {}

        if not isinstance(arguments, dict):
            raise TypeError(
                "Tool arguments must be provided as a dictionary."
            )

        return tool.handler(**arguments)


# ============================================================
# DEFAULT TOOL REGISTRY
# ============================================================

def create_default_registry() -> ToolRegistry:
    """
    Create the canonical AgenticOS tool registry.

    This function intentionally contains only registrations.

    Actual implementations will be connected incrementally as
    legacy bot.py functionality is migrated into proper tool modules.
    """

    registry = ToolRegistry()

    return registry


# ============================================================
# DEVELOPMENT / SELF TEST
# ============================================================

if __name__ == "__main__":
    def test_tool(message: str = "hello") -> str:
        return f"TEST_OK: {message}"

    registry = create_default_registry()

    registry.register(
        name="test_tool",
        description="Simple registry self-test tool.",
        handler=test_tool,
    )

    assert registry.has("test_tool")
    assert registry.get("test_tool") is not None
    assert registry.require("test_tool").name == "test_tool"

    result = registry.execute(
        "test_tool",
        {"message": "AgenticOS"},
    )

    assert result == "TEST_OK: AgenticOS"

    print("✅ ToolRegistry self-test passed.")
    print()
    print("Registered tools:")
    for tool in registry.describe():
        print(f"  - {tool['name']}: {tool['description']}")