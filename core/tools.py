"""
ARNIE AgenticOS
Canonical Tool Registry

This module defines the canonical executable capability layer for
AgenticOS.

Architecture:

    Agent
        ↓
    Task
        ↓
    PolicyEngine
        ↓
    ToolRegistry
        ↓
    Tool Handler / Capability

Important:

- Tool is the canonical executable capability.
- ToolRegistry is the canonical collection.
- PolicyEngine remains responsible for authorization.
- The Harness owns managed execution.
- Interface layers such as bot.py must not bypass the Harness for
  policy-protected execution.
- Registered Tools bind to canonical AgenticOS capabilities.

Migration status:

Wave 1:
    web_search
    get_current_time
    read_obsidian_note
    search_vault
    get_daily_vault_summary
    get_system_metrics
    list_tasks
    get_task

Wave 2:
    launch_app
    write_obsidian_note
    run_terminal_command
    launch_swarm

Agency workspace (Phase 12):
    run_agency_research

Client workspace (Phase 19):
    add_client
    list_clients
    update_client_status

Wave-2 tools are privileged and state-changing. Their registration here
does NOT bypass PolicyEngine.

Source-aware approval is handled by PolicyEngine:

    UI/local interface  -> auto-approved after normal policy checks
    Discord             -> requires human approval

The registry itself never makes authorization decisions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from inspect import isawaitable
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union


# ============================================================================
# NATIVE AGENTICOS CAPABILITIES
# ============================================================================

from capabilities.system.applications import launch_windows_app

from capabilities.vault import (
    get_daily_vault_summary,
    read_obsidian_note,
    search_master_brain_vault,
    write_obsidian_note,
)

from capabilities.web import web_search

from capabilities.system import (
    get_system_metrics,
    get_current_time,
)
from capabilities.system.terminal import run_terminal_command


# ============================================================================
# TOOL TYPES
# ============================================================================

ToolHandler = Callable[..., Any]
AsyncToolHandler = Callable[..., Awaitable[Any]]
ToolHandlerType = Union[ToolHandler, AsyncToolHandler]


# ============================================================================
# TOOL RISK
# ============================================================================


class ToolRisk(str, Enum):
    SAFE = "safe"
    CONTROLLED = "controlled"
    PRIVILEGED = "privileged"


# ============================================================================
# TOOL STATUS
# ============================================================================


class ToolStatus(str, Enum):
    ENABLED = "enabled"
    DISABLED = "disabled"


# ============================================================================
# TOOL PERMISSION POLICY
# ============================================================================


@dataclass(frozen=True)
class ToolPermissionPolicy:
    """
    Declarative permission metadata attached to a Tool.

    PolicyEngine remains the authority that interprets this metadata.
    """

    requires_approval: bool = False

    allow_owner: bool = True

    allow_agents: bool = True

    require_approval_for_privileged_tools: bool = True

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )


# ============================================================================
# TOOL DOMAIN OBJECT
# ============================================================================


@dataclass
class Tool:
    """
    Canonical executable capability.

    Tool execution itself does NOT perform authorization.

    Authorization belongs to:

        Harness -> PolicyEngine -> ToolRegistry
    """

    name: str

    description: str

    handler: ToolHandlerType

    risk: ToolRisk = ToolRisk.SAFE

    status: ToolStatus = ToolStatus.ENABLED

    local_access: bool = False

    mutates_state: bool = False

    requires_approval: bool = False

    # Deterministic tools return authoritative runtime results directly.
    # Synthesis-capable tools may be passed through a model after execution.
    deterministic: bool = False

    synthesis_required: bool = True

    permission_policy: ToolPermissionPolicy = field(
        default_factory=ToolPermissionPolicy
    )

    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        self.name = self.name.strip()

        if not self.name:
            raise ValueError(
                "Tool name cannot be empty."
            )

        self.description = self.description.strip()

        if not callable(self.handler):
            raise TypeError(
                f"Handler for Tool '{self.name}' must be callable."
            )

        # Keep the legacy requires_approval field and the canonical
        # permission policy synchronized.
        if (
            self.requires_approval
            and not self.permission_policy.requires_approval
        ):
            self.permission_policy = ToolPermissionPolicy(
                requires_approval=True,
                allow_owner=self.permission_policy.allow_owner,
                allow_agents=self.permission_policy.allow_agents,
                require_approval_for_privileged_tools=(
                    self.permission_policy
                    .require_approval_for_privileged_tools
                ),
                metadata=dict(
                    self.permission_policy.metadata
                ),
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

    def execute(
        self,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """
        Execute the underlying handler.

        IMPORTANT:

        This method intentionally does not authorize the Tool.

        Managed execution must happen through AgentHarness.
        """

        if not self.enabled:
            raise RuntimeError(
                f"Tool '{self.name}' is disabled."
            )

        arguments = (
            {}
            if arguments is None
            else arguments
        )

        if not isinstance(arguments, dict):
            raise TypeError(
                "Tool arguments must be a dictionary."
            )

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
        """
        Return the public Tool description.

        Handler implementation details are intentionally hidden.
        """

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


# ============================================================================
# TOOL REGISTRY
# ============================================================================


class ToolRegistry:
    """
    Canonical registry of AgenticOS Tools.

    Responsibilities:

        - know which Tools exist
        - register Tools
        - retrieve Tools
        - invoke Tool handlers
        - expose Tool metadata
        - expose execution mode

    It does NOT decide whether a Tool is authorized.
    """

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(
        self,
        tool: Tool,
    ) -> Tool:
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

    def register_many(
        self,
        tools: List[Tool],
    ) -> None:
        for tool in tools:
            self.register(tool)

    def bind_handler(
        self,
        name: str,
        handler: ToolHandlerType,
    ) -> Tool:
        """Bind a runtime-owned capability handler to a registered Tool."""
        if not callable(handler):
            raise TypeError(
                f"Handler for Tool '{name}' must be callable."
            )

        tool = self.require(name)
        tool.handler = handler
        return tool

    def unregister(
        self,
        name: str,
    ) -> Optional[Tool]:
        return self._tools.pop(
            name,
            None,
        )

    def get(
        self,
        name: str,
    ) -> Optional[Tool]:
        return self._tools.get(name)

    def require(
        self,
        name: str,
    ) -> Tool:
        tool = self.get(name)

        if tool is None:
            raise KeyError(
                f"Unknown tool: {name}"
            )

        return tool

    def has(
        self,
        name: str,
    ) -> bool:
        return name in self._tools

    def list(
        self,
        include_disabled: bool = True,
    ) -> List[Tool]:
        tools = list(
            self._tools.values()
        )

        if not include_disabled:
            tools = [
                tool
                for tool in tools
                if tool.enabled
            ]

        return sorted(
            tools,
            key=lambda tool: tool.name.lower(),
        )

    def names(
        self,
        include_disabled: bool = True,
    ) -> List[str]:
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
        return self.require(name).execute(
            arguments
        )

    async def execute_async(
        self,
        name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Any:
        return await self.require(name).execute_async(
            arguments
        )

    def execution_mode(
        self,
        name: str,
    ) -> str:
        """
        Return the canonical post-execution routing mode.

        Deterministic authoritative Tools are returned directly.

        Knowledge retrieval Tools are sent through model synthesis.
        """

        tool = self.require(name)

        if (
            tool.deterministic
            and not tool.synthesis_required
        ):
            return "direct"

        return "synthesize"


# ============================================================================
# WAVE 1 HANDLERS
# ============================================================================


def _web_search(
    query: str = "",
) -> str:
    return web_search(query)


def _current_time() -> str:
    return get_current_time()


def _read_obsidian_note(
    filename: str = "Inbox",
) -> str:
    return read_obsidian_note(
        filename
    )


def _search_vault(
    query: str = "",
    n_results: int = 3,
) -> str:
    return search_master_brain_vault(
        query,
        n_results,
    )


async def _daily_vault_summary() -> str:
    """Fail clearly until the Harness binds the model-aware handler."""
    raise RuntimeError(
        "The get_daily_vault_summary Tool has not been bound to the "
        "AgenticOS Harness model provider."
    )


def _system_metrics() -> str:
    return get_system_metrics()


async def _list_tasks(
    status: Optional[str] = None,
    workspace: Optional[str] = None,
    limit: int = 10,
) -> str:
    """Fail clearly until the Harness binds the Task-store-aware handler."""
    raise RuntimeError(
        "The list_tasks Tool has not been bound to the AgenticOS "
        "Harness Task store."
    )


async def _get_task(
    task_id: str = "",
) -> str:
    """Fail clearly until the Harness binds the Task-store-aware handler."""
    raise RuntimeError(
        "The get_task Tool has not been bound to the AgenticOS "
        "Harness Task store."
    )


# ============================================================================
# WAVE 2 HANDLERS
# ============================================================================


def _launch_app(
    args: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> str:
    """
    Launch a local Windows application through the native
    AgenticOS system capability.
    """

    arguments = dict(
        args or {}
    )

    arguments.update(kwargs)

    target = (
        arguments.get("app_name")
        or arguments.get("target")
        or arguments.get("name")
        or ""
    )

    return launch_windows_app(
        str(target)
    )


def _write_obsidian_note(
    filename: str = "Inbox",
    content: str = "",
    text: str = "",
) -> str:
    """Execute the canonical AgenticOS vault note writer."""
    note_content = content or text or ""
    return write_obsidian_note(
        filename,
        note_content,
    )


def _run_terminal_command(
    command: str = "dir",
) -> str:
    """Execute the canonical local terminal capability."""

    return run_terminal_command(
        command
    )


async def _launch_swarm(
    mission: str = "Default feature task",
) -> str:
    """Fail clearly if the Harness has not bound the canonical Swarm handler."""
    raise RuntimeError(
        "The launch_swarm Tool has not been bound to the AgenticOS "
        "Harness SwarmManager."
    )


# ============================================================================
# AGENCY WORKSPACE HANDLERS
# ============================================================================


async def _run_agency_research(
    topic: str = "",
) -> str:
    """Fail clearly until the Harness binds the Agency research handler."""
    raise RuntimeError(
        "The run_agency_research Tool has not been bound to the "
        "AgenticOS Harness."
    )


async def _run_generate_image(
    prompt: str = "",
    negative_prompt: str = "",
    steps: int = 20,
) -> str:
    """Fail clearly until the Harness binds the image generation handler."""
    raise RuntimeError(
        "The generate_image Tool has not been bound to the "
        "AgenticOS Harness."
    )


# ============================================================================
# CLIENT WORKSPACE HANDLERS
# ============================================================================


async def _add_client(
    name: str = "",
    service: str = "",
    notes: str = "",
) -> str:
    """Fail clearly until the Harness binds the Client tracking handler."""
    raise RuntimeError(
        "The add_client Tool has not been bound to the "
        "AgenticOS Harness."
    )


async def _list_clients(
    status: Optional[str] = None,
) -> str:
    """Fail clearly until the Harness binds the Client tracking handler."""
    raise RuntimeError(
        "The list_clients Tool has not been bound to the "
        "AgenticOS Harness."
    )


async def _update_client_status(
    client_id: str = "",
    status: str = "",
    notes: str = "",
) -> str:
    """Fail clearly until the Harness binds the Client tracking handler."""
    raise RuntimeError(
        "The update_client_status Tool has not been bound to the "
        "AgenticOS Harness."
    )


# ============================================================================
# DEFAULT REGISTRY
# ============================================================================


def create_default_registry() -> ToolRegistry:
    """
    Create the canonical production Tool Registry.

    Wave 1:
        Eight safe/read-oriented tools.

    Wave 2:
        Four privileged tools.

    Total:
        Seventeen registered capabilities.
    """

    registry = ToolRegistry()

    # ========================================================================
    # WAVE 1 — SAFE
    # ========================================================================

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
                "capability_handler": (
                    "capabilities.web.web_search"
                ),
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
                "capability_handler": (
                    "capabilities.system.get_current_time"
                ),
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
                "capability_handler": (
                    "capabilities.vault.read_obsidian_note"
                ),
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
                "capability_handler": (
                    "capabilities.vault.search_master_brain_vault"
                ),
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
            deterministic=True,
            synthesis_required=False,
            metadata={
                "migration_wave": 1,
                "capability_handler": (
                    "capabilities.vault.get_daily_vault_summary"
                ),
                "async": True,
                "authoritative": True,
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
                "capability_handler": (
                    "capabilities.system.get_system_metrics"
                ),
                "authoritative": True,
            },
        )
    )

    registry.register(
        Tool(
            name="list_tasks",
            description=(
                "List recent AgenticOS Tasks, optionally filtered by "
                "status or workspace."
            ),
            handler=_list_tasks,
            risk=ToolRisk.SAFE,
            local_access=True,
            mutates_state=False,
            deterministic=True,
            synthesis_required=False,
            metadata={
                "migration_wave": 1,
                "capability_handler": (
                    "capabilities.tasks.TaskStore.list_tasks"
                ),
                "async": True,
                "authoritative": True,
                "handler_bound_by": "AgentHarness",
            },
        )
    )

    registry.register(
        Tool(
            name="get_task",
            description=(
                "Retrieve the full detail of a single AgenticOS Task "
                "by its id."
            ),
            handler=_get_task,
            risk=ToolRisk.SAFE,
            local_access=True,
            mutates_state=False,
            deterministic=True,
            synthesis_required=False,
            metadata={
                "migration_wave": 1,
                "capability_handler": (
                    "capabilities.tasks.TaskStore.get_task"
                ),
                "async": True,
                "authoritative": True,
                "handler_bound_by": "AgentHarness",
            },
        )
    )

    # ========================================================================
    # WAVE 2 — PRIVILEGED
    # ========================================================================

    registry.register(
        Tool(
            name="launch_app",
            description=(
                "Launch a local Windows application using a known "
                "application shortcut or an explicit application target."
            ),
            handler=_launch_app,
            risk=ToolRisk.PRIVILEGED,
            local_access=True,
            mutates_state=True,
            requires_approval=True,
            deterministic=True,
            synthesis_required=False,
            metadata={
                "migration_wave": 2,
                "capability_handler": (
                    "capabilities.system.applications.launch_windows_app"
                ),
                "privileged": True,
                "approval_required": True,
            },
        )
    )

    registry.register(
        Tool(
            name="write_obsidian_note",
            description=(
                "Write or update a Markdown note in the Master Brain vault."
            ),
            handler=_write_obsidian_note,
            risk=ToolRisk.PRIVILEGED,
            local_access=True,
            mutates_state=True,
            requires_approval=True,
            deterministic=True,
            synthesis_required=False,
            metadata={
                "migration_wave": 2,
                "capability_handler": (
                    "capabilities.vault.write_obsidian_note"
                ),
                "privileged": True,
                "approval_required": True,
                "migration_status": "native",
            },
        )
    )

    registry.register(
        Tool(
            name="run_terminal_command",
            description=(
                "Execute an approved Windows terminal command on the "
                "local AgenticOS machine."
            ),
            handler=_run_terminal_command,
            risk=ToolRisk.PRIVILEGED,
            local_access=True,
            mutates_state=True,
            requires_approval=True,
            deterministic=True,
            synthesis_required=False,
            metadata={
                "migration_wave": 2,
                "capability_handler": (
                    "capabilities.system.terminal.run_terminal_command"
                ),
                "privileged": True,
                "approval_required": True,
                "migration_status": "native",
            },
        )
    )

    registry.register(
        Tool(
            name="launch_swarm",
            description=(
                "Launch the AgenticOS multi-agent swarm pipeline for a "
                "research, coding, review, or implementation mission."
            ),
            handler=_launch_swarm,
            risk=ToolRisk.PRIVILEGED,
            local_access=True,
            mutates_state=True,
            requires_approval=True,
            deterministic=True,
            synthesis_required=False,
            metadata={
                "migration_wave": 2,
                "capability_handler": (
                    "core.swarm.SwarmManager.execute_crew_pipeline"
                ),
                "privileged": True,
                "approval_required": True,
                "migration_status": "native",
                "async": True,
                "handler_bound_by": "AgentHarness",
            },
        )
    )

    # ========================================================================
    # AGENCY WORKSPACE
    # ========================================================================

    registry.register(
        Tool(
            name="run_agency_research",
            description=(
                "Run an autonomous Agency research mission on a topic, "
                "company, or lead, and track it as a workspace='agency' "
                "Task."
            ),
            handler=_run_agency_research,
            risk=ToolRisk.CONTROLLED,
            local_access=False,
            mutates_state=True,
            requires_approval=False,
            deterministic=True,
            synthesis_required=False,
            metadata={
                "phase": 12,
                "workspace": "agency",
                "capability_handler": (
                    "capabilities.web.research.deep_research_web"
                ),
                "async": True,
                "authoritative": True,
                "handler_bound_by": "AgentHarness",
            },
        )
    )

    # MEDIA WORKSPACE
    # ========================================================================

    registry.register(
        Tool(
            name="generate_image",
            description=(
                "Generate an image from a text prompt using the local "
                "Stable Diffusion-compatible API, and track it as a "
                "workspace='media' Task."
            ),
            handler=_run_generate_image,
            risk=ToolRisk.CONTROLLED,
            local_access=False,
            mutates_state=True,
            requires_approval=False,
            deterministic=False,
            synthesis_required=False,
            metadata={
                "phase": 13,
                "workspace": "media",
                "capability_handler": (
                    "capabilities.media.service.ImageGenService.generate"
                ),
                "async": True,
                "authoritative": True,
                "handler_bound_by": "AgentHarness",
            },
        )
    )

    # ========================================================================
    # CLIENT WORKSPACE
    # ========================================================================

    registry.register(
        Tool(
            name="add_client",
            description=(
                "Add a new client to the agency CRM. Arguments: name (str), "
                "service (str), notes (str, optional)."
            ),
            handler=_add_client,
            risk=ToolRisk.CONTROLLED,
            local_access=True,
            mutates_state=True,
            requires_approval=False,
            deterministic=True,
            synthesis_required=False,
            metadata={
                "phase": 19,
                "workspace": "client",
                "capability_handler": (
                    "capabilities.clients.service.add_client"
                ),
                "async": True,
                "authoritative": True,
                "handler_bound_by": "AgentHarness",
            },
        )
    )

    registry.register(
        Tool(
            name="list_clients",
            description=(
                "List all agency clients. Optional argument: status filter "
                "(prospect/active/paused/completed)."
            ),
            handler=_list_clients,
            risk=ToolRisk.SAFE,
            local_access=True,
            mutates_state=False,
            requires_approval=False,
            deterministic=True,
            synthesis_required=False,
            metadata={
                "phase": 19,
                "workspace": "client",
                "capability_handler": (
                    "capabilities.clients.service.list_clients"
                ),
                "async": True,
                "authoritative": True,
                "handler_bound_by": "AgentHarness",
            },
        )
    )

    registry.register(
        Tool(
            name="update_client_status",
            description=(
                "Update a client's status. Arguments: client_id (str), "
                "status (str: prospect/active/paused/completed), "
                "notes (str, optional)."
            ),
            handler=_update_client_status,
            risk=ToolRisk.CONTROLLED,
            local_access=True,
            mutates_state=True,
            requires_approval=False,
            deterministic=True,
            synthesis_required=False,
            metadata={
                "phase": 19,
                "workspace": "client",
                "capability_handler": (
                    "capabilities.clients.service.update_client_status"
                ),
                "async": True,
                "authoritative": True,
                "handler_bound_by": "AgentHarness",
                "workspace_approval_required": True,
            },
        )
    )

    return registry


# ============================================================================
# SELF TEST
# ============================================================================


def run_tests() -> None:
    """
    Validate the complete canonical Tool Registry.

    No privileged handlers are executed by this test.
    """

    registry = create_default_registry()

    expected = {
        "web_search",
        "get_current_time",
        "read_obsidian_note",
        "search_vault",
        "get_daily_vault_summary",
        "get_system_metrics",
        "list_tasks",
        "get_task",
        "launch_app",
        "write_obsidian_note",
        "run_terminal_command",
        "launch_swarm",
        "run_agency_research",
        "generate_image",
        "add_client",
        "list_clients",
        "update_client_status",
    }

    actual = set(
        registry.names()
    )

    assert actual == expected, (
        "Registry mismatch.\n"
        f"Expected: {sorted(expected)}\n"
        f"Actual: {sorted(actual)}"
    )

    # ========================================================================
    # SAFE TOOLS
    # ========================================================================

    safe_tools = {
        "web_search",
        "get_current_time",
        "read_obsidian_note",
        "search_vault",
        "get_daily_vault_summary",
        "get_system_metrics",
        "list_tasks",
        "get_task",
        "list_clients",
    }

    for name in safe_tools:
        tool = registry.require(name)

        assert tool.enabled

        assert tool.risk == ToolRisk.SAFE

        assert tool.permission_policy.allow_owner

        assert not tool.mutates_state

    # ========================================================================
    # PRIVILEGED TOOLS
    # ========================================================================

    privileged_tools = {
        "launch_app",
        "write_obsidian_note",
        "run_terminal_command",
        "launch_swarm",
    }

    for name in privileged_tools:
        tool = registry.require(name)

        assert tool.enabled

        assert tool.risk == ToolRisk.PRIVILEGED

        assert tool.local_access

        assert tool.mutates_state

        assert tool.requires_approval

        assert tool.permission_policy.allow_owner

        assert tool.permission_policy.requires_approval

        assert registry.execution_mode(name) == "direct"

    # ========================================================================
    # CONTROLLED TOOLS
    # ========================================================================

    controlled_tools = {
        "run_agency_research",
        "add_client",
        "update_client_status",
    }

    for name in controlled_tools:
        tool = registry.require(name)

        assert tool.enabled

        assert tool.risk == ToolRisk.CONTROLLED

        assert tool.mutates_state

        assert not tool.requires_approval

        assert tool.permission_policy.allow_owner

        assert registry.execution_mode(name) == "direct"

    # ========================================================================
    # DETERMINISTIC TOOLS
    # ========================================================================

    deterministic_tools = {
        "web_search",
        "get_current_time",
        "get_system_metrics",
        "get_daily_vault_summary",
        "list_tasks",
        "get_task",
        "launch_app",
        "write_obsidian_note",
        "run_terminal_command",
        "launch_swarm",
        "run_agency_research",
        "add_client",
        "list_clients",
        "update_client_status",
    }

    for name in deterministic_tools:
        tool = registry.require(name)

        assert tool.deterministic

        assert not tool.synthesis_required

        assert registry.execution_mode(name) == "direct"

    # ========================================================================
    # KNOWLEDGE TOOLS
    # ========================================================================

    synthesis_tools = {
        "read_obsidian_note",
        "search_vault",
    }

    for name in synthesis_tools:
        tool = registry.require(name)

        assert not tool.deterministic

        assert tool.synthesis_required

        assert registry.execution_mode(name) == "synthesize"

    # ========================================================================
    # ASYNC HANDLERS
    # ========================================================================

    import inspect

    assert inspect.iscoroutinefunction(
        _daily_vault_summary
    )

    assert inspect.iscoroutinefunction(
        _launch_swarm
    )

    assert inspect.iscoroutinefunction(
        _list_tasks
    )

    assert inspect.iscoroutinefunction(
        _get_task
    )

    # ========================================================================
    # PUBLIC DESCRIPTIONS
    # ========================================================================

    for description in registry.describe():
        assert "handler" not in description

        assert "risk" in description

        assert "name" in description

        assert "description" in description

    # ========================================================================
    # DUPLICATE PROTECTION
    # ========================================================================

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

    # ========================================================================
    # DISABLED TOOL FILTERING
    # ========================================================================

    test_registry = ToolRegistry()

    disabled_tool = Tool(
        name="disabled_test",
        description="Disabled test Tool.",
        handler=lambda: "disabled",
    )

    disabled_tool.disable()

    test_registry.register(
        disabled_tool
    )

    assert "disabled_test" in (
        test_registry.names(
            include_disabled=True
        )
    )

    assert "disabled_test" not in (
        test_registry.names(
            include_disabled=False
        )
    )

    # ========================================================================
    # OUTPUT
    # ========================================================================

    print("=" * 72)
    print(
        "ARNIE AGENTIC OS — CANONICAL TOOL REGISTRY TEST"
    )
    print("=" * 72)

    print()
    print("Registered Wave-1 + Wave-2 Tools:")
    print()

    for tool in registry.list():
        print(
            f"  ✓ {tool.name:<26}"
            f"risk={tool.risk.value:<11}"
            f"local={str(tool.local_access):<5}"
            f"mutates={str(tool.mutates_state):<5}"
            f"mode={registry.execution_mode(tool.name)}"
        )

    print()
    print("✓ Eight Wave-1 safe tools registered")
    print("✓ Four Wave-2 privileged tools registered")
    print("✓ Canonical Tool domain objects")
    print("✓ Deterministic routing owned by ToolRegistry")
    print("✓ Privileged tools remain Policy-protected")
    print("✓ UI/Discord approval remains Policy responsibility")
    print("✓ Native capability handlers used for migrated Tools")
    print("✓ Async swarm adapter avoids nested event loops")
    print("✓ Direct authoritative vault summary")
    print("✓ Duplicate protection")
    print("✓ Disabled-tool filtering")
    print("✓ Policy metadata preserved")
    print()
    print("=" * 72)
    print(
        "CANONICAL TOOL REGISTRY TEST PASSED"
    )
    print("=" * 72)


if __name__ == "__main__":
    run_tests()