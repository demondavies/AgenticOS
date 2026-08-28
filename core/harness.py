"""
ARNIE Agentic OS
Agent Harness

This is the first working orchestration layer.

The Harness coordinates:

    Task
      Ã¢â€ â€œ
    Agent
      Ã¢â€ â€œ
    Model Provider
      Ã¢â€ â€œ
    Model
      Ã¢â€ â€œ
    Result
      Ã¢â€ â€œ
    Events

IMPORTANT:

This is deliberately a SMALL first implementation.

It does not yet:
    - replace bot.py
    - persist tasks
    - execute arbitrary tools without Policy authorization
    - manage the swarm outside the canonical Tool boundary
    - manage Discord
    - manage FastAPI
    - manage voice
    - manage Master Brain

Those systems will be migrated onto the Harness incrementally.

The purpose of this module is to prove the central architectural loop.
"""

from __future__ import annotations

import asyncio

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .config import DEFAULT_MODEL

from .agents import (
    Agent,
    AgentRegistry,
    AgentStatus,
    create_default_agent_registry,
)

from .events import (
    Event,
    EventBus,
    EventCategory,
    EventNames,
    EventSeverity,
    create_event,
)

from .models import (
    ModelMessage,
    ModelProvider,
    ModelRegistry,
    ModelRequest,
    ModelResponse,
    create_default_model_registry,
)

from .tasks import (
    Task,
    TaskExecution,
    TaskResult,
    TaskStatus,
)

from .tools import (
    ToolRegistry,
    create_default_registry,
)

from .policy import (
    PolicyDecision,
    PolicyEngine,
    PolicyRequest,
)

from capabilities.memory import (
    MemoryStore,
)
from capabilities.voice import VoiceService
from capabilities.web.research import deep_research_web
from .swarm import SwarmManager


# ============================================================================
# HARNESS RESULT
# ============================================================================


@dataclass
class HarnessResult:
    """
    Result returned by the Harness after executing a Task.
    """

    success: bool

    task: Task

    execution: Optional[TaskExecution] = None

    response: Optional[ModelResponse] = None

    error: Optional[str] = None


# ============================================================================
# AGENT HARNESS
# ============================================================================


class AgentHarness:
    """
    Central orchestration layer for ARNIE.

    Responsibilities:

        - receive Tasks
        - select Agents
        - resolve Model Providers
        - execute model requests
        - emit Events
        - update Task state
        - return structured results

    The Harness does not know about:
        - Discord
        - FastAPI
        - Kokoro
        - SQLite implementation details
        - ChromaDB

    Interfaces and infrastructure sit outside this layer.
    """

    def __init__(
        self,
        agent_registry: Optional[AgentRegistry] = None,
        model_registry: Optional[ModelRegistry] = None,
        event_bus: Optional[EventBus] = None,
        tool_registry: Optional[ToolRegistry] = None,
        memory_store: Optional[MemoryStore] = None,
        voice_service: Optional[VoiceService] = None,
    ) -> None:
        self.agents = (
            agent_registry
            if agent_registry is not None
            else create_default_agent_registry()
        )

        self.models = (
            model_registry
            if model_registry is not None
            else create_default_model_registry()
        )

        self.events = (
            event_bus
            if event_bus is not None
            else EventBus()
        )

        self.tools = (
            tool_registry
            if tool_registry is not None
            else create_default_registry()
        )

        # Policy is the authorization boundary for Tool execution.
        # The PolicyEngine never executes Tools; it only decides whether the
        # Harness may hand an authorized Tool to the ToolRegistry.
        self.policy = PolicyEngine()

        # Memory is an AgenticOS capability. The Harness receives it as a
        # dependency; it does not own SQLite implementation details.
        self.memory = (
            memory_store
            if memory_store is not None
            else MemoryStore()
        )

        # Voice is an AgenticOS capability. The Harness exposes the
        # orchestration seam; microphone/STT implementation stays in
        # capabilities.voice.
        self.voice = (
            voice_service
            if voice_service is not None
            else VoiceService()
        )

        # Swarm is an AgenticOS orchestration capability. The Harness owns
        # its lifecycle and injects the canonical model and web capability
        # boundaries. Interface adapters never implement swarm orchestration.
        self.swarm_orchestrator = SwarmManager(
            model_chat=self._swarm_model_chat,
            research_web=deep_research_web,
        )

        # launch_swarm is a canonical Tool. Bind the Harness-owned Swarm
        # capability into the ToolRegistry so normal Policy authorization
        # remains in force before the handler can execute.
        self.tools.bind_handler(
            "launch_swarm",
            self.execute_swarm,
        )

        # get_daily_vault_summary needs a model provider, so the Harness owns
        # the provider selection and binds the capability through the Tool
        # Registry. The Vault capability never constructs its own registry.
        self.tools.bind_handler(
            "get_daily_vault_summary",
            self.execute_daily_vault_summary,
        )

    async def _swarm_model_chat(
        self,
        messages: List[Dict[str, str]],
        *,
        model: str = DEFAULT_MODEL,
        capability: str = "reasoning",
    ) -> str:
        """Run a Swarm model request through the canonical ModelProvider."""
        provider = self.select_model_provider()

        request = ModelRequest(
            messages=[
                ModelMessage(
                    role=message["role"],
                    content=message["content"],
                    name=message.get("name"),
                )
                for message in messages
            ],
            capability=capability,
            model=model,
            metadata={"source": "agenticos_swarm"},
        )

        response = await asyncio.to_thread(
            provider.chat,
            request,
        )
        return response.content

    async def execute_daily_vault_summary(self) -> str:
        """Execute the canonical Vault summary with Harness-owned model routing."""
        from capabilities.vault import get_daily_vault_summary

        agent = self.agents.find_by_name("Coordinator")
        if agent is None:
            raise RuntimeError("No Coordinator Agent is registered.")

        provider = self.select_model_provider(agent)
        model = agent.preferred_model() or DEFAULT_MODEL

        return await get_daily_vault_summary(
            model_provider=provider,
            model=model,
        )

    async def execute_swarm(
        self,
        mission: str = "Default feature task",
    ) -> str:
        """Execute the canonical SwarmManager through the Tool boundary."""
        result = await self.swarm_orchestrator.execute_crew_pipeline(
            mission
        )

        return (
            "SWARM PIPELINE COMPLETE!\n"
            f"Task ID: {result['task_id']}\n"
            "Artifact staged in memory. "
            f"Default filename: {result['default_filename']}"
        )

    # ---------------------------------------------------------------------
    # Agent selection
    # ---------------------------------------------------------------------

    def select_agent(
        self,
        task: Task,
        agent_name: Optional[str] = None,
    ) -> Agent:
        """
        Select an Agent for a Task.

        Selection order:

            1. Explicit Agent name
            2. Task assigned_agent
            3. Task metadata capability
            4. Task metadata agent
            5. Fallback to Coordinator
        """

        # --------------------------------------------------------------
        # Explicit Agent selection
        # --------------------------------------------------------------

        if agent_name:
            agent = self.agents.find_by_name(agent_name)

            if agent is None:
                raise ValueError(
                    f"Agent '{agent_name}' was not found."
                )

            return agent

        # --------------------------------------------------------------
        # Task assignment
        # --------------------------------------------------------------

        if task.assigned_agent:
            try:
                return self.agents.get(task.assigned_agent)
            except KeyError:
                # The assigned value might be a human-readable Agent name.
                agent = self.agents.find_by_name(
                    task.assigned_agent
                )

                if agent is not None:
                    return agent

                raise ValueError(
                    f"Assigned Agent '{task.assigned_agent}' "
                    f"was not found."
                )

        # --------------------------------------------------------------
        # Capability-based selection
        # --------------------------------------------------------------

        capability = task.metadata.get("agent_capability")

        if capability:
            candidates = self.agents.find_by_capability(
                capability
            )

            available = [
                agent
                for agent in candidates
                if agent.status == AgentStatus.IDLE
            ]

            if available:
                return available[0]

            if candidates:
                return candidates[0]

        # --------------------------------------------------------------
        # Explicit metadata Agent
        # --------------------------------------------------------------

        metadata_agent = task.metadata.get("agent")

        if metadata_agent:
            agent = self.agents.find_by_name(
                metadata_agent
            )

            if agent is not None:
                return agent

        # --------------------------------------------------------------
        # Default
        # --------------------------------------------------------------

        coordinator = self.agents.find_by_name(
            "Coordinator"
        )

        if coordinator is None:
            raise RuntimeError(
                "No Coordinator Agent is registered."
            )

        return coordinator

    # ---------------------------------------------------------------------
    # Model provider selection
    # ---------------------------------------------------------------------

    def select_model_provider(
        self,
        agent: Optional[Agent] = None,
    ) -> ModelProvider:
        """
        Select a ModelProvider for an Agent.

        Currently returns the first registered provider.
        Future versions will route by agent capability profile.
        """

        providers = self.models.list_providers()

        if not providers:
            raise RuntimeError(
                "No Model Providers are registered."
            )

        return self.models.get(providers[0])

    # ---------------------------------------------------------------------
    # Model interface
    # ---------------------------------------------------------------------

    @staticmethod
    def _coerce_model_messages(messages: List[Any]) -> List[ModelMessage]:
        """Convert interface message dictionaries into canonical messages."""
        result: List[ModelMessage] = []

        for message in messages:
            if isinstance(message, ModelMessage):
                result.append(message)
                continue

            if not isinstance(message, dict):
                raise TypeError(
                    "Model messages must be ModelMessage objects or dictionaries."
                )

            result.append(
                ModelMessage(
                    role=str(message["role"]),
                    content=str(message["content"]),
                    name=message.get("name"),
                )
            )

        return result

    async def chat(
        self,
        messages: List[Any],
        model: Optional[str] = None,
        capability: str = "conversation",
        source: str = "harness.chat",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Execute a non-streaming model request through AgenticOS."""
        task = Task(
            title="Model chat",
            description="Execute a conversational model request.",
            workspace="development",
            metadata={
                "source": source,
                "capability": capability,
            },
        )
        agent = self.select_agent(task)
        provider = self.select_model_provider(agent)
        selected_model = model or agent.preferred_model()

        request_metadata = dict(metadata or {})
        request_metadata.update({
            "source": source,
            "capability": capability,
        })

        request = ModelRequest(
            messages=self._coerce_model_messages(messages),
            capability=capability,
            model=selected_model,
            metadata=request_metadata,
        )

        response = await asyncio.to_thread(provider.chat, request)
        return response.content

    def stream(
        self,
        messages: List[Any],
        model: Optional[str] = None,
        capability: str = "conversation",
        source: str = "harness.stream",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Return a provider-independent model stream through AgenticOS."""
        task = Task(
            title="Model stream",
            description="Execute a streaming conversational model request.",
            workspace="development",
            metadata={
                "source": source,
                "capability": capability,
            },
        )
        agent = self.select_agent(task)
        provider = self.select_model_provider(agent)
        selected_model = model or agent.preferred_model()

        request_metadata = dict(metadata or {})
        request_metadata.update({
            "source": source,
            "capability": capability,
        })

        request = ModelRequest(
            messages=self._coerce_model_messages(messages),
            capability=capability,
            model=selected_model,
            metadata=request_metadata,
        )

        return provider.stream(request)

    # ---------------------------------------------------------------------
    # Tool execution and post-tool routing
    # ---------------------------------------------------------------------

    def _authorize_tool(
        self,
        tool_name: str,
        *,
        task: Task,
        agent: Agent,
        source: str = "harness",
        user_approved: bool = False,
    ):
        """Evaluate Tool authorization without executing the Tool."""
        tool = self.tools.get(tool_name)
        if tool is None:
            raise KeyError(f"Unknown tool: {tool_name}")

        result = self.policy.evaluate(
            PolicyRequest(
                agent=agent,
                task=task,
                tool=tool,
                source=source,
                user_approved=user_approved,
            )
        )

        if result.decision == PolicyDecision.DENY:
            raise PermissionError(
                f"Policy denied Tool '{tool_name}': "
                f"{result.message}"
            )

        return result

    def execute_tool(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        *,
        task: Optional[Task] = None,
        agent: Optional[Agent] = None,
        source: str = "harness",
        user_approved: bool = False,
    ) -> Any:
        """Authorize and execute a registered Tool through the Harness."""
        if task is None or agent is None:
            raise ValueError(
                "Policy-protected Tool execution requires both task and agent. "
                "Use execute_tool_for_task() for a managed execution context."
            )

        self._authorize_tool(
            tool_name,
            task=task,
            agent=agent,
            source=source,
            user_approved=user_approved,
        )
        return self.tools.execute(tool_name, arguments)

    async def execute_tool_async(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        *,
        task: Optional[Task] = None,
        agent: Optional[Agent] = None,
        source: str = "harness",
        user_approved: bool = False,
    ) -> Any:
        """Async counterpart to policy-protected Tool execution."""
        if task is None or agent is None:
            raise ValueError(
                "Policy-protected Tool execution requires both task and agent. "
                "Use execute_tool_for_task() for a managed execution context."
            )

        self._authorize_tool(
            tool_name,
            task=task,
            agent=agent,
            source=source,
            user_approved=user_approved,
        )
        return await self.tools.execute_async(tool_name, arguments)

    def execute_tool_for_task(
        self,
        task: Task,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        *,
        agent_name: Optional[str] = None,
        source: str = "harness",
        user_approved: bool = False,
    ) -> Any:
        """Select an Agent, enforce Policy, then execute the Tool."""
        agent = self.select_agent(task, agent_name=agent_name)
        return self.execute_tool(
            tool_name,
            arguments,
            task=task,
            agent=agent,
            source=source,
            user_approved=user_approved,
        )

    async def execute_tool_for_task_async(
        self,
        task: Task,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        *,
        agent_name: Optional[str] = None,
        source: str = "harness",
        user_approved: bool = False,
    ) -> Any:
        """Async managed Tool execution through the Policy boundary."""
        agent = self.select_agent(task, agent_name=agent_name)
        return await self.execute_tool_async(
            tool_name,
            arguments,
            task=task,
            agent=agent,
            source=source,
            user_approved=user_approved,
        )

    def tool_execution_mode(self, tool_name: str) -> str:
        """
        Return the canonical post-execution routing mode.

        The Harness owns this decision. Interfaces such as bot.py must not
        maintain their own hard-coded lists of deterministic tools.
        """
        return self.tools.execution_mode(tool_name)

    # ---------------------------------------------------------------------
    # Voice
    # ---------------------------------------------------------------------

    def record_voice(self) -> bytes:
        """Record local microphone audio through the Voice capability."""
        return self.voice.record()

    def transcribe_voice(self, audio_bytes: bytes) -> str:
        """Transcribe captured audio through the Voice capability."""
        return self.voice.transcribe(audio_bytes)

    # ---------------------------------------------------------------------
    # Memory
    # ---------------------------------------------------------------------

    def initialize_memory(self) -> None:
        """Initialize the configured AgenticOS memory store."""
        self.memory.init_db()

    def get_memory(
        self,
        channel_id: str,
        limit: int = 20,
    ) -> List[Dict[str, str]]:
        """Retrieve recent persistent conversation memory."""
        return self.memory.get_recent_history(channel_id, limit)

    def save_memory(
        self,
        channel_id: str,
        user_id: str,
        role: str,
        content: str,
    ) -> None:
        """Persist one conversation message through the memory capability."""
        self.memory.save_message(
            channel_id,
            user_id,
            role,
            content,
        )

    async def compact_memory(
        self,
        channel_id: str,
        keep_recent: int = 10,
    ) -> str:
        """Compact persistent channel memory when requested by the caller."""
        return await self.memory.compact_channel_memory(
            channel_id,
            keep_recent,
        )

    def run_tool(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute a tool and return structured runtime evidence.

        Deterministic tools are authoritative runtime capabilities and should
        be returned directly. Synthesis-capable tools are explicitly marked
        for later model synthesis by the caller.
        """
        task = Task(
            title=f"Tool execution: {tool_name}",
            description=f"Execute registered Tool '{tool_name}'.",
            workspace="development",
        )
        agent = self.select_agent(task)
        result = self.execute_tool(
            tool_name,
            arguments,
            task=task,
            agent=agent,
            source="harness.run_tool",
        )
        return {
            "tool": tool_name,
            "mode": self.tool_execution_mode(tool_name),
            "result": result,
        }

    # ---------------------------------------------------------------------
    # Task execution
    # ---------------------------------------------------------------------

    def run(
        self,
        task: Task,
        agent_name: Optional[str] = None,
    ) -> HarnessResult:
        """
        Execute one Task through the Harness.

        This is the first complete ARNIE orchestration path.
        """

        execution: Optional[TaskExecution] = None
        response: Optional[ModelResponse] = None

        try:
            # ==========================================================
            # Queue
            # ==========================================================

            if task.status == TaskStatus.CREATED:
                task.queue()

            self.events.publish(
                create_event(
                    name=EventNames.TASK_QUEUED,
                    category=EventCategory.TASK,
                    source="harness",
                    task_id=task.id,
                    correlation_id=task.id,
                    data={
                        "title": task.title,
                    },
                )
            )

            # ==========================================================
            # Agent selection
            # ==========================================================

            agent = self.select_agent(
                task,
                agent_name=agent_name,
            )

            # ==========================================================
            # Assign
            # ==========================================================

            task.assign(agent.id)

            self.events.publish(
                create_event(
                    name=EventNames.TASK_ASSIGNED,
                    category=EventCategory.TASK,
                    source="harness",
                    task_id=task.id,
                    correlation_id=task.id,
                    agent_id=agent.id,
                    data={
                        "agent": agent.name,
                    },
                )
            )

            # ==========================================================
            # Start Agent
            # ==========================================================

            agent.start()

            self.events.publish(
                create_event(
                    name=EventNames.AGENT_STARTED,
                    category=EventCategory.AGENT,
                    source="harness",
                    task_id=task.id,
                    correlation_id=task.id,
                    agent_id=agent.id,
                    data={
                        "agent": agent.name,
                        "role": agent.role,
                    },
                )
            )

            # ==========================================================
            # Start Task
            # ==========================================================

            task.start()

            self.events.publish(
                create_event(
                    name=EventNames.TASK_STARTED,
                    category=EventCategory.TASK,
                    source="harness",
                    task_id=task.id,
                    correlation_id=task.id,
                    agent_id=agent.id,
                )
            )

            # ==========================================================
            # Create Execution
            # ==========================================================

            execution = TaskExecution(
                task_id=task.id,
                agent_id=agent.id,
            )

            execution.start()

            # ==========================================================
            # Select Model Provider
            # ==========================================================

            provider = self.select_model_provider(agent)

            preferred_model = agent.preferred_model()

            execution.provider = provider.name
            execution.model = preferred_model

            # ==========================================================
            # Build Model Request
            # ==========================================================

            system_prompt = agent.system_prompt

            user_prompt = task.description

            if task.inputs:
                user_prompt += (
                    "\n\nTask inputs:\n"
                    f"{self._format_inputs(task.inputs)}"
                )

            request = ModelRequest(
                messages=[
                    ModelMessage(
                        role="system",
                        content=system_prompt,
                    ),
                    ModelMessage(
                        role="user",
                        content=user_prompt,
                    ),
                ],
                capability=agent.model_capability(),
                model=preferred_model,
                metadata={
                    "task_id": task.id,
                    "execution_id": execution.id,
                    "agent_id": agent.id,
                },
            )

            # ==========================================================
            # Model Requested
            # ==========================================================

            self.events.publish(
                create_event(
                    name=EventNames.MODEL_REQUESTED,
                    category=EventCategory.MODEL,
                    source="harness",
                    task_id=task.id,
                    execution_id=execution.id,
                    agent_id=agent.id,
                    correlation_id=task.id,
                    data={
                        "provider": provider.name,
                        "model": preferred_model,
                        "capability": agent.model_capability(),
                    },
                )
            )

            # ==========================================================
            # Execute Model
            # ==========================================================

            response = provider.chat(request)

            # ==========================================================
            # Model Completed
            # ==========================================================

            self.events.publish(
                create_event(
                    name=EventNames.MODEL_COMPLETED,
                    category=EventCategory.MODEL,
                    source=provider.name,
                    task_id=task.id,
                    execution_id=execution.id,
                    agent_id=agent.id,
                    correlation_id=task.id,
                    data={
                        "provider": response.provider,
                        "model": response.model,
                    },
                )
            )

            # ==========================================================
            # Build Task Result
            # ==========================================================

            result = TaskResult(
                success=True,
                output=response.content,
                metadata={
                    "model": response.model,
                    "provider": response.provider,
                },
            )

            # ==========================================================
            # Complete Execution
            # ==========================================================

            execution.complete(result)

            # ==========================================================
            # Verify
            # ==========================================================

            task.begin_verification()

            self.events.publish(
                create_event(
                    name=EventNames.TASK_VERIFYING,
                    category=EventCategory.TASK,
                    source="harness",
                    task_id=task.id,
                    execution_id=execution.id,
                    agent_id=agent.id,
                    correlation_id=task.id,
                )
            )

            # ----------------------------------------------------------
            # Version 1 verification
            #
            # For now, a successful model response is considered valid.
            #
            # Real verification will be added later.
            # ----------------------------------------------------------

            task.complete(result)

            # ==========================================================
            # Agent Finished
            # ==========================================================

            agent.finish()

            self.events.publish(
                create_event(
                    name=EventNames.AGENT_COMPLETED,
                    category=EventCategory.AGENT,
                    source="harness",
                    task_id=task.id,
                    execution_id=execution.id,
                    agent_id=agent.id,
                    correlation_id=task.id,
                )
            )

            # ==========================================================
            # Task Completed
            # ==========================================================

            self.events.publish(
                create_event(
                    name=EventNames.TASK_COMPLETED,
                    category=EventCategory.TASK,
                    source="harness",
                    task_id=task.id,
                    execution_id=execution.id,
                    agent_id=agent.id,
                    correlation_id=task.id,
                    data={
                        "title": task.title,
                    },
                )
            )

            return HarnessResult(
                success=True,
                task=task,
                execution=execution,
                response=response,
            )

        except Exception as exc:

            error_message = str(exc)

            # ----------------------------------------------------------
            # Attempt to recover Agent state.
            # ----------------------------------------------------------

            try:
                if (
                    agent_name is not None
                    or task.assigned_agent is not None
                ):
                    agent = self.select_agent(
                        task,
                        agent_name=agent_name,
                    )

                    agent.mark_error()

                    self.events.publish(
                        create_event(
                            name=EventNames.AGENT_FAILED,
                            category=EventCategory.AGENT,
                            source="harness",
                            task_id=task.id,
                            execution_id=(
                                execution.id
                                if execution
                                else None
                            ),
                            agent_id=agent.id,
                            correlation_id=task.id,
                            severity=EventSeverity.ERROR,
                            data={
                                "error": error_message,
                            },
                        )
                    )
            except Exception:
                # Do not mask the original failure.
                pass

            # ----------------------------------------------------------
            # Fail Execution
            # ----------------------------------------------------------

            if execution is not None:
                try:
                    if execution.status.value == "running":
                        execution.fail(error_message)
                except Exception:
                    pass

            # ----------------------------------------------------------
            # Fail Task
            # ----------------------------------------------------------

            try:
                if not task.is_terminal():
                    task.fail(
                        error_message,
                        retry=False,
                    )
            except Exception:
                pass

            # ----------------------------------------------------------
            # Emit Task Failure
            # ----------------------------------------------------------

            self.events.publish(
                create_event(
                    name=EventNames.TASK_FAILED,
                    category=EventCategory.TASK,
                    source="harness",
                    task_id=task.id,
                    execution_id=(
                        execution.id
                        if execution
                        else None
                    ),
                    correlation_id=task.id,
                    severity=EventSeverity.ERROR,
                    data={
                        "error": error_message,
                    },
                )
            )

            return HarnessResult(
                success=False,
                task=task,
                execution=execution,
                response=response,
                error=error_message,
            )

    # ---------------------------------------------------------------------
    # Utilities
    # ---------------------------------------------------------------------

    @staticmethod
    def _format_inputs(
        inputs: Dict[str, Any],
    ) -> str:
        """
        Convert Task input data into a simple prompt representation.

        This is intentionally basic.

        Structured prompt construction will become its own service later.
        """

        lines: List[str] = []

        for key, value in inputs.items():
            lines.append(
                f"- {key}: {value}"
            )

        return "\n".join(lines)


# ============================================================================
# DEVELOPMENT TEST
# ============================================================================


def run_tool_tests() -> None:
    """Verify the Harness owns tool execution-mode decisions."""
    harness = AgentHarness()

    assert isinstance(harness.memory, MemoryStore)
    assert isinstance(harness.voice, VoiceService)
    assert callable(harness.record_voice)
    assert callable(harness.transcribe_voice)
    assert callable(harness.get_memory)
    assert callable(harness.save_memory)
    assert callable(harness.compact_memory)

    assert harness.tool_execution_mode("web_search") == "direct"
    assert harness.tool_execution_mode("get_current_time") == "direct"
    assert harness.tool_execution_mode("get_system_metrics") == "direct"

    assert harness.tool_execution_mode("search_vault") == "synthesize"
    assert harness.tool_execution_mode("read_obsidian_note") == "synthesize"
    assert harness.tool_execution_mode("get_daily_vault_summary") == "direct"
    assert harness.tools.require("get_daily_vault_summary").handler.__self__ is harness
    assert harness.tools.require("get_daily_vault_summary").handler.__func__ is AgentHarness.execute_daily_vault_summary

    # Wave-2 privileged tools must be registered centrally.
    for name in {
        "launch_app",
        "write_obsidian_note",
        "run_terminal_command",
        "launch_swarm",
    }:
        tool = harness.tools.get(name)
        assert tool is not None
        assert tool.risk.value == "privileged"
        assert tool.local_access is True
        assert tool.mutates_state is True

    # Do not execute real Wave-2 side effects during the core contract test.
    # the legacy runtime into the core test. We only verify routing ownership.

    print("Ã¢Å“â€œ Harness tool-routing contract passed")


def run_policy_tests() -> None:
    """Verify that Harness Tool execution is gated by PolicyEngine."""
    harness = AgentHarness()

    task = Task(
        title="Policy harness test",
        description="Test policy-protected Tool execution.",
        workspace="development",
        metadata={"agent": "Researcher"},
    )
    agent = harness.select_agent(task)

    # Researcher is explicitly permitted to use web_search.
    result = harness._authorize_tool(
        "web_search",
        task=task,
        agent=agent,
        source="harness.test",
    )
    assert result.decision == PolicyDecision.ALLOW

    # ------------------------------------------------------------------
    # Wave 2: privileged tools
    #
    # The UI/local interface is trusted and therefore auto-approved after
    # all normal Policy DENY checks pass. Discord is intentionally NOT a
    # trusted source and must stop at APPROVAL_REQUIRED.
    # ------------------------------------------------------------------
    trusted_local = Task(
        title="Trusted local Wave-2 policy test",
        description="Test source-aware approval for privileged tools.",
        workspace="system",
        metadata={"agent": "Coordinator"},
    )
    coordinator = harness.select_agent(trusted_local)

    privileged_tools = {
        "launch_app",
        "write_obsidian_note",
        "run_terminal_command",
        "launch_swarm",
    }

    for tool_name in privileged_tools:
        tool = harness.tools.get(tool_name)
        assert tool is not None, f"Missing Wave-2 Tool: {tool_name}"
        assert tool.risk.value == "privileged"
        assert tool.local_access is True
        assert tool.mutates_state is True

        local_result = harness._authorize_tool(
            tool_name,
            task=trusted_local,
            agent=coordinator,
            source="ui",
        )
        assert local_result.decision == PolicyDecision.ALLOW
        assert local_result.metadata.get("source_auto_approved") is True

        discord_result = harness._authorize_tool(
            tool_name,
            task=trusted_local,
            agent=coordinator,
            source="discord",
        )
        assert discord_result.approval_required, (
            f"Policy bypass: Discord auto-approved {tool_name}"
        )

        approved_result = harness._authorize_tool(
            tool_name,
            task=trusted_local,
            agent=coordinator,
            source="discord",
            user_approved=True,
        )
        assert approved_result.decision == PolicyDecision.ALLOW

    print("✓ Wave-2 privileged tools auto-approve from UI")
    print("✓ Wave-2 privileged tools require approval from Discord")

    # An unapproved Tool must not be authorized.
    # The Coordinator is intentionally tested against a Tool it is not
    # permitted to use. We only exercise the authorization boundary here;
    # no real Tool handler is executed.
    blocked = Task(
        title="Policy denial test",
        description="Test denied Tool authorization.",
        workspace="development",
        metadata={"agent": "Coordinator"},
    )
    blocked_coordinator = harness.select_agent(blocked)

    denied_tool = harness.tools.get("web_search")
    assert denied_tool is not None, "Missing web_search Tool for policy test"

    # Coordinator is allowed to use the safe Wave-1 tools in normal runtime,
    # so web_search is no longer a valid denial probe. Temporarily use a
    # synthetic Tool that is absent from the Coordinator's permission set.
    from .tools import Tool, ToolRisk

    synthetic_denied_tool = Tool(
        name="policy_denied_test",
        description="Synthetic Tool used only to verify Policy denial.",
        handler=lambda: (_ for _ in ()).throw(
            AssertionError("Denied Tool handler was executed.")
        ),
        risk=ToolRisk.SAFE,
    )
    harness.tools.register(synthetic_denied_tool)

    try:
        harness._authorize_tool(
            "policy_denied_test",
            task=blocked,
            agent=blocked_coordinator,
            source="harness.test",
        )
    except PermissionError:
        pass
    else:
        raise AssertionError("Policy bypass: denied Tool authorized")

    print("✓ Harness Policy boundary passed")


def run_tests() -> None:
    """
    End-to-end Harness test.

    This test DOES communicate with the locally installed Ollama provider.

    It intentionally uses a tiny prompt so that we can prove the complete
    architecture without involving the existing bot.py.
    """

    run_tool_tests()
    run_policy_tests()

    print("=" * 60)
    print("ARNIE AGENT HARNESS TEST")
    print("=" * 60)

    # ------------------------------------------------------------------
    # Capture Events
    # ------------------------------------------------------------------

    captured_events: List[Event] = []

    event_bus = EventBus()

    event_bus.subscribe(
        lambda event: captured_events.append(event)
    )

    # ------------------------------------------------------------------
    # Create Harness
    # ------------------------------------------------------------------

    harness = AgentHarness(
        event_bus=event_bus,
    )

    print("\nProviders:")
    for provider in harness.models.list_providers():
        print(f"  Ã¢Å“â€œ {provider}")

    print("\nAgents:")

    for agent in harness.agents.list_agents():
        print(
            f"  Ã¢Å“â€œ {agent.name} "
            f"({agent.model_capability()})"
        )

    # ------------------------------------------------------------------
    # Create Task
    # ------------------------------------------------------------------

    task = Task(
        title="Harness smoke test",
        description=(
            "Explain what a GPU is in one short sentence."
        ),
        workspace="development",
        metadata={
            "agent_capability": "reasoning",
        },
    )

    print("\nTask:")
    print(f"  ID: {task.id}")
    print(f"  Title: {task.title}")

    # ------------------------------------------------------------------
    # Run Task
    # ------------------------------------------------------------------

    print("\nRunning Harness...")

    result = harness.run(task)

    # ------------------------------------------------------------------
    # Result
    # ------------------------------------------------------------------

    if not result.success:
        print()
        print("HARNESS TEST FAILED")
        print(f"Error: {result.error}")
        raise SystemExit(1)

    print("\nModel response:")
    print("-" * 60)

    if result.response:
        print(result.response.content)

    print("-" * 60)

    # ------------------------------------------------------------------
    # Validate Task
    # ------------------------------------------------------------------

    assert result.success is True
    assert result.task.status == TaskStatus.COMPLETED
    assert result.execution is not None
    assert result.execution.status.value == "completed"
    assert result.response is not None
    assert result.response.content.strip()

    print("\nTask:")
    print(f"  Status: {result.task.status.value}")

    print("\nExecution:")
    print(f"  Status: {result.execution.status.value}")
    print(f"  Agent:  {result.execution.agent_id}")
    print(f"  Model:  {result.execution.model}")
    print(f"  Provider: {result.execution.provider}")

    # ------------------------------------------------------------------
    # Validate Events
    # ------------------------------------------------------------------

    print("\nEvents:")

    for event in captured_events:
        print(
            f"  Ã¢Å“â€œ {event.name}"
        )

    required_events = {
        EventNames.TASK_QUEUED,
        EventNames.TASK_ASSIGNED,
        EventNames.AGENT_STARTED,
        EventNames.TASK_STARTED,
        EventNames.MODEL_REQUESTED,
        EventNames.MODEL_COMPLETED,
        EventNames.TASK_VERIFYING,
        EventNames.AGENT_COMPLETED,
        EventNames.TASK_COMPLETED,
    }

    captured_names = {
        event.name
        for event in captured_events
    }

    missing = required_events - captured_names

    assert not missing, (
        "Missing expected events: "
        + ", ".join(sorted(missing))
    )

    # ------------------------------------------------------------------
    # Final
    # ------------------------------------------------------------------

    print()
    print("=" * 60)
    print("AGENT HARNESS TEST PASSED")
    print("=" * 60)


if __name__ == "__main__":
    run_tests()
