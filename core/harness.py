"""
ARNIE Agentic OS
Agent Harness

This is the first working orchestration layer.

The Harness coordinates:

    Task
      ↓
    Agent
      ↓
    Model Provider
      ↓
    Model
      ↓
    Result
      ↓
    Events

IMPORTANT:

This is deliberately a SMALL first implementation.

It does not yet:
    - replace bot.py
    - persist tasks
    - execute arbitrary tools
    - run the existing swarm
    - manage Discord
    - manage FastAPI
    - manage voice
    - manage Master Brain

Those systems will be migrated onto the Harness incrementally.

The purpose of this module is to prove the central architectural loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agents import (
    Agent,
    AgentRegistry,
    AgentStatus,
    create_default_agent_registry,
)

from events import (
    Event,
    EventBus,
    EventCategory,
    EventNames,
    EventSeverity,
    create_event,
)

from models import (
    ModelMessage,
    ModelProvider,
    ModelRegistry,
    ModelRequest,
    ModelResponse,
    create_default_model_registry,
)

from tasks import (
    Task,
    TaskExecution,
    TaskResult,
    TaskStatus,
)


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
        - SQLite
        - ChromaDB

    Interfaces and infrastructure sit outside this layer.
    """

    def __init__(
        self,
        agent_registry: Optional[AgentRegistry] = None,
        model_registry: Optional[ModelRegistry] = None,
        event_bus: Optional[EventBus] = None,
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
        agent: Agent,
    ) -> ModelProvider:
        """
        Select a ModelProvider for an Agent.

        Version 1:

            Use Ollama.

        The provider is still abstracted behind ModelProvider, so future
        routing can be introduced without changing the Harness interface.
        """

        # For now ARNIE has one provider.

        providers = self.models.list_providers()

        if not providers:
            raise RuntimeError(
                "No Model Providers are registered."
            )

        # Prefer Ollama while it is our current local provider.

        if "ollama" in providers:
            return self.models.get("ollama")

        # Otherwise use the first available provider.

        return self.models.get(providers[0])

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


def run_tests() -> None:
    """
    End-to-end Harness test.

    This test DOES communicate with the locally installed Ollama provider.

    It intentionally uses a tiny prompt so that we can prove the complete
    architecture without involving the existing bot.py.
    """

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
        print(f"  ✓ {provider}")

    print("\nAgents:")

    for agent in harness.agents.list_agents():
        print(
            f"  ✓ {agent.name} "
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
            f"  ✓ {event.name}"
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