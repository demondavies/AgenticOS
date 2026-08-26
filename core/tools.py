"""
ARNIE AgenticOS
Safe Tool Registry

This module is the canonical registry for the first migration wave of
ARNIE's existing read-oriented tools.

Important:
- Tool is the canonical executable capability.
- ToolRegistry is the canonical collection.
- PolicyEngine remains responsible for authorization.
- The legacy bot implementation remains the handler owner for now.
- Lazy handler adapters avoid importing bot.py during AgenticOS startup,
  preventing a circular import while we migrate the monolith incrementally.

Migration wave 1:
    web_search
    get_current_time
    read_obsidian_note
    search_vault
    get_daily_vault_summary
    get_system_metrics

Privileged/state-changing tools are intentionally NOT registered here yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from inspect import isawaitable
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union


ToolHandler = Callable[..., Any]
AsyncToolHandler = Callable[..., Awaitable[Any]]
ToolHandlerType = Union[ToolHandler, AsyncToolHandler]


class ToolRisk(str, Enum):
    SAFE = "safe"
    CONTROLLED = "controlled"
    PRIVILEGED = "privileged"


class ToolStatus(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"


@dataclass(frozen=True)
class ToolPermissionPolicy:
    requires_approval: bool = False
    allow_owner: bool = True
    allow_agents: bool = True
    require_approval_for_privileged_tools: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Tool:
    name: str
    description: str
    handler: ToolHandlerType
    risk: ToolRisk = ToolRisk.SAFE
    status: ToolStatus = ToolStatus.ENABLED
    local_access: bool = False
    mutates_state: bool = False
    requires_approval: bool = False

    # Execution semantics belong to the Tool contract, not to bot.py.
    # Deterministic tools return authoritative runtime results directly.
    # Tools marked synthesis_required may be passed to a model after execution.
    deterministic: bool = False
    synthesis_required: bool = True

    permission_policy: ToolPermissionPolicy = field(
        default_factory=ToolPermissionPolicy
    )
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.name = self.name.strip()
        if not self.name:
            raise ValueError("Tool name cannot be empty.")
        self.description = self.description.strip()
        if not callable(self.handler):
            raise TypeError(
                f"Handler for Tool '{self.name}' must be callable."
            )

        if self.requires_approval and not self.permission_policy.requires_approval:
            self.permission_policy = ToolPermissionPolicy(
                requires_approval=True,
                allow_owner=self.permission_policy.allow_owner,
                allow_agents=self.permission_policy.allow_agents,
                require_approval_for_privileged_tools=(
                    self.permission_policy.require_approval_for_privileged_tools
                ),
                metadata=dict(self.permission_policy.metadata),
            )

    @property
    def enabled(self) -> bool:
        return self.status == ToolStatus.ENABLED

    @property
    def disabled(self) -> bool:
        return self.status == ToolStatus.DISABLED

    def enable(self) -> None:
        self.status = ToolStatus.ENABLED

    def disable(self) -> None:
        self.status = ToolStatus.DISABLED

    def execute(self, arguments: Optional[Dict[str, Any]] = None) -> Any:
        """
        Execute the handler.

        Authorization is deliberately NOT performed here.
        The Harness / PolicyEngine owns that responsibility.
        """
        if not self.enabled:
            raise RuntimeError(f"Tool '{self.name}' is disabled.")

        arguments = {} if arguments is None else arguments

        if not isinstance(arguments, dict):
            raise TypeError("Tool arguments must be a dictionary.")

        return self.handler(**arguments)

    async def execute_async(
        self,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Any:
        result = self.execute(arguments)

        if isawaitable(result):
            return await result

        return result

    def describe(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "risk": self.risk.value,
            "status": self.status.value,
            "local_access": self.local_access,
            "mutates_state": self.mutates_state,
            "requires_approval": (
                self.requires_approval
                or self.permission_policy.requires_approval
            ),
            "deterministic": self.deterministic,
            "synthesis_required": self.synthesis_required,
            "metadata": dict(self.metadata),
        }


class ToolRegistry:
    """
    Canonical registry of AgenticOS Tools.

    It knows what exists and how to invoke it.
    It does not decide whether execution is permitted.
    """

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if not isinstance(tool, Tool):
            raise TypeError(
                "ToolRegistry.register() requires a Tool object."
            )

        if tool.name in self._tools:
            raise ValueError(
                f"Tool already registered: {tool.name}"
            )

        self._tools[tool.name] = tool
        return tool

    def register_many(self, tools: List[Tool]) -> None:
        for tool in tools:
            self.register(tool)

    def unregister(self, name: str) -> Optional[Tool]:
        return self._tools.pop(name, None)

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def require(self, name: str) -> Tool:
        tool = self.get(name)

        if tool is None:
            raise KeyError(f"Unknown tool: {name}")

        return tool

    def has(self, name: str) -> bool:
        return name in self._tools

    def list(self, include_disabled: bool = True) -> List[Tool]:
        tools = list(self._tools.values())

        if not include_disabled:
            tools = [tool for tool in tools if tool.enabled]

        return sorted(
            tools,
            key=lambda tool: tool.name.lower(),
        )

    def names(self, include_disabled: bool = True) -> List[str]:
        return [
            tool.name
            for tool in self.list(
                include_disabled=include_disabled
            )
        ]

    def describe(
        self,
        include_disabled: bool = True,
    ) -> List[Dict[str, Any]]:
        return [
            tool.describe()
            for tool in self.list(
                include_disabled=include_disabled
            )
        ]

    def execute(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Any:
        return self.require(name).execute(arguments)

    async def execute_async(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Any:
        return await self.require(name).execute_async(arguments)

    def execution_mode(self, name: str) -> str:
        """
        Return the canonical post-execution routing mode.

        This is intentionally a property of the registered Tool rather than
        a hard-coded list in bot.py.
        """
        tool = self.require(name)

        if tool.deterministic and not tool.synthesis_required:
            return "direct"

        return "synthesize"


# ============================================================================
# LAZY LEGACY HANDLER ADAPTERS
# ============================================================================

def _legacy_module():
    """
    Import the legacy bot only when a registered tool is actually executed.

    This is a temporary migration seam. Once the handlers move into
    AgenticOS tool modules, these adapters disappear.
    """
    import bot
    return bot


def _web_search(query: str = "") -> str:
    return _legacy_module().perform_web_search(query)


def _current_time() -> str:
    return _legacy_module().get_current_time()


def _read_obsidian_note(filename: str = "Inbox") -> str:
    return _legacy_module().read_obsidian_note(filename)


def _search_vault(
    query: str = "",
    n_results: int = 3,
) -> str:
    return _legacy_module().search_master_brain_vault(
        query,
        n_results,
    )


async def _daily_vault_summary() -> str:
    return await _legacy_module().get_daily_vault_summary()


def _system_metrics() -> str:
    return _legacy_module().get_system_metrics_telemetry()


# ============================================================================
# SAFE TOOL DEFINITIONS
# ============================================================================

def create_default_registry() -> ToolRegistry:
    """
    Create the first real production registry.

    Only read-oriented tools are included in migration wave 1.
    """

    registry = ToolRegistry()

    registry.register(
        Tool(
            name="web_search",
            description=(
                "Search the live web for current information and return "
                "a concise set of relevant results."
            ),
            handler=_web_search,
            risk=ToolRisk.SAFE,
            local_access=False,
            mutates_state=False,
            deterministic=True,
            synthesis_required=False,
            metadata={
                "migration_wave": 1,
                "legacy_handler": "perform_web_search",
            },
        )
    )

    registry.register(
        Tool(
            name="get_current_time",
            description=(
                "Return the current local system time and date."
            ),
            handler=_current_time,
            risk=ToolRisk.SAFE,
            local_access=False,
            mutates_state=False,
            deterministic=True,
            synthesis_required=False,
            metadata={
                "migration_wave": 1,
                "legacy_handler": "get_current_time",
            },
        )
    )

    registry.register(
        Tool(
            name="read_obsidian_note",
            description=(
                "Read the contents of a Markdown note from the "
                "Master Brain vault."
            ),
            handler=_read_obsidian_note,
            risk=ToolRisk.SAFE,
            local_access=True,
            mutates_state=False,
            deterministic=False,
            synthesis_required=True,
            metadata={
                "migration_wave": 1,
                "legacy_handler": "read_obsidian_note",
            },
        )
    )

    registry.register(
        Tool(
            name="search_vault",
            description=(
                "Search the Master Brain vector vault for relevant "
                "past notes, project context, and stored knowledge."
            ),
            handler=_search_vault,
            risk=ToolRisk.SAFE,
            local_access=True,
            mutates_state=False,
            deterministic=False,
            synthesis_required=True,
            metadata={
                "migration_wave": 1,
                "legacy_handler": "search_master_brain_vault",
            },
        )
    )

    registry.register(
        Tool(
            name="get_daily_vault_summary",
            description=(
                "Return an on-demand executive summary of the current "
                "Master Brain vault."
            ),
            handler=_daily_vault_summary,
            risk=ToolRisk.SAFE,
            local_access=True,
            mutates_state=False,
            deterministic=False,
            synthesis_required=True,
            metadata={
                "migration_wave": 1,
                "legacy_handler": "get_daily_vault_summary",
                "async": True,
            },
        )
    )

    registry.register(
        Tool(
            name="get_system_metrics",
            description=(
                "Return current CPU, RAM, and local hardware telemetry."
            ),
            handler=_system_metrics,
            risk=ToolRisk.SAFE,
            local_access=True,
            mutates_state=False,
            deterministic=True,
            synthesis_required=False,
            metadata={
                "migration_wave": 1,
                "legacy_handler": "get_system_metrics_telemetry",
            },
        )
    )

    return registry


# ============================================================================
# SELF TEST
# ============================================================================

def run_tests() -> None:
    import asyncio

    registry = create_default_registry()

    expected = {
        "web_search",
        "get_current_time",
        "read_obsidian_note",
        "search_vault",
        "get_daily_vault_summary",
        "get_system_metrics",
    }

    actual = set(registry.names())

    assert actual == expected, (
        f"Registry mismatch.\nExpected: {sorted(expected)}"
        f"\nActual: {sorted(actual)}"
    )

    for name in expected:
        tool = registry.require(name)

        assert tool.enabled
        assert tool.risk == ToolRisk.SAFE
        assert tool.permission_policy.allow_owner
        assert not tool.mutates_state

    # Deterministic runtime capabilities must bypass model synthesis.
    for name in {"web_search", "get_current_time", "get_system_metrics"}:
        tool = registry.require(name)
        assert tool.deterministic
        assert not tool.synthesis_required
        assert registry.execution_mode(name) == "direct"

    # Knowledge tools remain synthesis-capable during this migration wave.
    for name in {
        "read_obsidian_note",
        "search_vault",
        "get_daily_vault_summary",
    }:
        tool = registry.require(name)
        assert not tool.deterministic
        assert tool.synthesis_required
        assert registry.execution_mode(name) == "synthesize"

    # Verify the async adapter shape without importing bot.py.
    import inspect
    assert inspect.iscoroutinefunction(_daily_vault_summary)

    # Verify all descriptions are serializable and handlers are hidden.
    for description in registry.describe():
        assert "handler" not in description
        assert description["risk"] == "safe"

    # Verify duplicate protection.
    duplicate_rejected = False

    try:
        registry.register(
            Tool(
                name="web_search",
                description="Duplicate test.",
                handler=_web_search,
            )
        )
    except ValueError:
        duplicate_rejected = True

    assert duplicate_rejected

    print("=" * 64)
    print("ARNIE SAFE TOOL REGISTRY TEST")
    print("=" * 64)
    print()
    print("Registered migration-wave-1 tools:")

    for tool in registry.list():
        print(
            f"  ✓ {tool.name:<24}"
            f" risk={tool.risk.value:<8}"
            f" local={str(tool.local_access):<5}"
            f" mutates={str(tool.mutates_state):<5}"
        )

    print()
    print("✓ Six safe tools registered")
    print("✓ Canonical Tool domain objects")
    print("✓ Lazy legacy handlers")
    print("✓ Async vault-summary adapter")
    print("✓ Duplicate protection")
    print("✓ Policy metadata preserved")
    print()
    print("==============================================================")
    print("SAFE TOOL REGISTRY TEST PASSED")
    print("==============================================================")


if __name__ == "__main__":
    run_tests()
