"""
ARNIE Agentic OS
Event Domain Model

Events are ARNIE's observable nervous system.

Core components will eventually emit events such as:

    task.created
    task.started
    agent.started
    model.requested
    tool.called
    tool.completed
    task.completed

Consumers such as the UI, logger, audit system, Discord interface, or future
VPS workers can subscribe to those events without becoming tightly coupled
to the component that produced them.

IMPORTANT:
- Events describe something that happened.
- Events do not execute business logic.
- Event producers should not need to know who is listening.
- This first implementation is synchronous and in-memory.
- Durable event persistence and async transport can be added later without
  changing the basic Event contract.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4


# ============================================================================
# HELPERS
# ============================================================================


def utc_now() -> datetime:
    """Return the current UTC time."""
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    """Create a readable unique identifier."""
    return f"{prefix}_{uuid4().hex}"


# ============================================================================
# EVENT CATEGORY
# ============================================================================


class EventCategory(str, Enum):
    """
    Broad event categories.

    These make filtering easier without requiring consumers to understand
    every individual event name.
    """

    SYSTEM = "system"
    TASK = "task"
    AGENT = "agent"
    MODEL = "model"
    TOOL = "tool"
    MEMORY = "memory"
    ARTIFACT = "artifact"
    APPROVAL = "approval"
    VOICE = "voice"
    WORKSPACE = "workspace"
    SECURITY = "security"


# ============================================================================
# EVENT SEVERITY
# ============================================================================


class EventSeverity(str, Enum):
    """
    Event importance.

    This is useful for logs, alerts and future dashboard filtering.
    """

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# ============================================================================
# EVENT
# ============================================================================


@dataclass(frozen=True)
class Event:
    """
    Immutable record describing something that happened inside ARNIE.

    name:
        Specific event identifier.

        Examples:
            task.created
            task.started
            agent.started
            tool.called
            model.completed

    category:
        Broad event family.

    source:
        Component that emitted the event.

        Examples:
            harness
            task_engine
            researcher
            ollama
            terminal

    correlation_id:
        Connects related events across one larger operation.

        Eventually this may normally be the Task ID.

    task_id / execution_id / agent_id:
        Optional direct references useful for tracing.

    data:
        Structured event payload.

    metadata:
        Additional non-essential tracing information.
    """

    name: str

    category: EventCategory

    source: str

    id: str = field(default_factory=lambda: new_id("event"))

    severity: EventSeverity = EventSeverity.INFO

    created_at: datetime = field(default_factory=utc_now)

    correlation_id: Optional[str] = None

    task_id: Optional[str] = None

    execution_id: Optional[str] = None

    agent_id: Optional[str] = None

    data: Dict[str, Any] = field(default_factory=dict)

    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert the Event to a JSON-friendly dictionary."""

        result = asdict(self)

        result["category"] = self.category.value
        result["severity"] = self.severity.value
        result["created_at"] = self.created_at.isoformat()

        return result


# ============================================================================
# EVENT HANDLER
# ============================================================================


EventHandler = Callable[[Event], None]


# ============================================================================
# SUBSCRIPTION
# ============================================================================


@dataclass
class EventSubscription:
    """
    Internal subscription definition.

    event_name:
        Exact event to listen for.

        None means listen to every event.

    category:
        Optional category filter.

    handler:
        Function called when an event matches.
    """

    handler: EventHandler

    id: str = field(default_factory=lambda: new_id("sub"))

    event_name: Optional[str] = None

    category: Optional[EventCategory] = None

    active: bool = True

    def matches(self, event: Event) -> bool:
        """Return True when this subscription accepts the Event."""

        if not self.active:
            return False

        if (
            self.event_name is not None
            and self.event_name != event.name
        ):
            return False

        if (
            self.category is not None
            and self.category != event.category
        ):
            return False

        return True


# ============================================================================
# EVENT BUS
# ============================================================================


class EventBus:
    """
    Simple synchronous event bus.

    This is deliberately small.

    Today:

        Component
            ↓
        EventBus
            ↓
        Python subscribers

    Later:

        Component
            ↓
        EventBus
            ├── structured logs
            ├── SQLite event history
            ├── WebSocket/SSE
            ├── UI
            ├── notifications
            └── remote workers

    Producers do not need to change when those consumers are added.
    """

    def __init__(self) -> None:
        self._subscriptions: Dict[str, EventSubscription] = {}

    # ---------------------------------------------------------------------
    # Subscription
    # ---------------------------------------------------------------------

    def subscribe(
        self,
        handler: EventHandler,
        event_name: Optional[str] = None,
        category: Optional[EventCategory] = None,
    ) -> str:
        """
        Subscribe to events.

        With no filters, the handler receives every event.
        """

        if not callable(handler):
            raise TypeError("Event handler must be callable.")

        subscription = EventSubscription(
            handler=handler,
            event_name=event_name,
            category=category,
        )

        self._subscriptions[subscription.id] = subscription

        return subscription.id

    def unsubscribe(
        self,
        subscription_id: str,
    ) -> bool:
        """
        Remove a subscription.

        Returns True if the subscription existed.
        """

        if subscription_id not in self._subscriptions:
            return False

        del self._subscriptions[subscription_id]

        return True

    def clear(self) -> None:
        """Remove all subscriptions."""
        self._subscriptions.clear()

    # ---------------------------------------------------------------------
    # Publishing
    # ---------------------------------------------------------------------

    def publish(
        self,
        event: Event,
    ) -> List[Exception]:
        """
        Publish an Event to matching subscribers.

        One broken subscriber must not stop other subscribers from receiving
        the Event.

        Subscriber exceptions are returned to the caller rather than raised
        immediately.
        """

        errors: List[Exception] = []

        # Snapshot the values so a handler can safely subscribe/unsubscribe
        # while an event is being published.
        subscriptions = list(self._subscriptions.values())

        for subscription in subscriptions:
            if not subscription.matches(event):
                continue

            try:
                subscription.handler(event)
            except Exception as exc:
                errors.append(exc)

        return errors

    # ---------------------------------------------------------------------
    # Introspection
    # ---------------------------------------------------------------------

    def subscription_count(self) -> int:
        """Return the number of current subscriptions."""
        return len(self._subscriptions)

    def list_subscriptions(self) -> List[EventSubscription]:
        """Return current subscriptions."""
        return list(self._subscriptions.values())


# ============================================================================
# EVENT FACTORY
# ============================================================================


def create_event(
    name: str,
    category: EventCategory,
    source: str,
    *,
    severity: EventSeverity = EventSeverity.INFO,
    correlation_id: Optional[str] = None,
    task_id: Optional[str] = None,
    execution_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Event:
    """
    Convenience factory for creating Events.

    Keeping creation centralized gives us somewhere to add common tracing
    behaviour later.
    """

    if not name or not name.strip():
        raise ValueError("Event name cannot be empty.")

    if not source or not source.strip():
        raise ValueError("Event source cannot be empty.")

    return Event(
        name=name.strip(),
        category=category,
        source=source.strip(),
        severity=severity,
        correlation_id=correlation_id,
        task_id=task_id,
        execution_id=execution_id,
        agent_id=agent_id,
        data=data or {},
        metadata=metadata or {},
    )


# ============================================================================
# STANDARD EVENT NAMES
# ============================================================================


class EventNames:
    """
    Standard event names used by ARNIE.

    Centralizing these reduces typo-driven event names such as:

        task.complete
        task.completed
        tasks.completed

    Existing components can gradually migrate to this vocabulary.
    """

    # System
    SYSTEM_STARTED = "system.started"
    SYSTEM_STOPPED = "system.stopped"
    SYSTEM_ERROR = "system.error"

    # Tasks
    TASK_CREATED = "task.created"
    TASK_QUEUED = "task.queued"
    TASK_ASSIGNED = "task.assigned"
    TASK_STARTED = "task.started"
    TASK_WAITING = "task.waiting"
    TASK_VERIFYING = "task.verifying"
    TASK_APPROVAL_REQUIRED = "task.approval_required"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_CANCELLED = "task.cancelled"
    TASK_REJECTED = "task.rejected"
    TASK_RETRYING = "task.retrying"

    # Agents
    AGENT_STARTED = "agent.started"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"

    # Models
    MODEL_REQUESTED = "model.requested"
    MODEL_STREAM_STARTED = "model.stream_started"
    MODEL_COMPLETED = "model.completed"
    MODEL_FAILED = "model.failed"

    # Tools
    TOOL_CALLED = "tool.called"
    TOOL_COMPLETED = "tool.completed"
    TOOL_FAILED = "tool.failed"
    TOOL_APPROVAL_REQUIRED = "tool.approval_required"

    # Memory
    MEMORY_STORED = "memory.stored"
    MEMORY_RETRIEVED = "memory.retrieved"
    MEMORY_COMPACTED = "memory.compacted"

    # Artifacts
    ARTIFACT_CREATED = "artifact.created"
    ARTIFACT_STAGED = "artifact.staged"
    ARTIFACT_APPROVED = "artifact.approved"
    ARTIFACT_REJECTED = "artifact.rejected"

    # Voice
    VOICE_TRANSCRIBED = "voice.transcribed"
    VOICE_SYNTHESIS_STARTED = "voice.synthesis_started"
    VOICE_SYNTHESIS_COMPLETED = "voice.synthesis_completed"


# ============================================================================
# DEVELOPMENT TESTS
# ============================================================================


def run_tests() -> None:
    """
    Dependency-free tests for ARNIE's Event domain model.
    """

    print("=" * 60)
    print("ARNIE EVENT DOMAIN MODEL TEST")
    print("=" * 60)

    # ------------------------------------------------------------------
    # Test 1: Event creation
    # ------------------------------------------------------------------

    event = create_event(
        name=EventNames.TASK_CREATED,
        category=EventCategory.TASK,
        source="test",
        task_id="task_test",
        correlation_id="task_test",
        data={
            "title": "Test task",
        },
    )

    assert event.id.startswith("event_")
    assert event.name == "task.created"
    assert event.category == EventCategory.TASK
    assert event.task_id == "task_test"

    print("✓ Event creation")

    # ------------------------------------------------------------------
    # Test 2: Serialization
    # ------------------------------------------------------------------

    serialized = event.to_dict()

    assert isinstance(serialized, dict)
    assert serialized["name"] == "task.created"
    assert serialized["category"] == "task"
    assert serialized["severity"] == "info"
    assert isinstance(serialized["created_at"], str)

    print("✓ Event serialization")

    # ------------------------------------------------------------------
    # Test 3: Event bus
    # ------------------------------------------------------------------

    bus = EventBus()

    received: List[Event] = []

    subscription_id = bus.subscribe(
        lambda item: received.append(item)
    )

    assert subscription_id.startswith("sub_")
    assert bus.subscription_count() == 1

    bus.publish(event)

    assert len(received) == 1
    assert received[0] is event

    print("✓ Event publishing")

    # ------------------------------------------------------------------
    # Test 4: Event-name filtering
    # ------------------------------------------------------------------

    task_started_events: List[Event] = []

    bus.subscribe(
        lambda item: task_started_events.append(item),
        event_name=EventNames.TASK_STARTED,
    )

    bus.publish(event)

    assert len(task_started_events) == 0

    started = create_event(
        name=EventNames.TASK_STARTED,
        category=EventCategory.TASK,
        source="test",
        task_id="task_test",
    )

    bus.publish(started)

    assert len(task_started_events) == 1

    print("✓ Event-name filtering")

    # ------------------------------------------------------------------
    # Test 5: Category filtering
    # ------------------------------------------------------------------

    tool_events: List[Event] = []

    bus.subscribe(
        lambda item: tool_events.append(item),
        category=EventCategory.TOOL,
    )

    bus.publish(started)

    assert len(tool_events) == 0

    tool_event = create_event(
        name=EventNames.TOOL_CALLED,
        category=EventCategory.TOOL,
        source="test_tool",
    )

    bus.publish(tool_event)

    assert len(tool_events) == 1

    print("✓ Category filtering")

    # ------------------------------------------------------------------
    # Test 6: Broken subscriber isolation
    # ------------------------------------------------------------------

    healthy_events: List[Event] = []

    def broken_handler(_: Event) -> None:
        raise RuntimeError("Intentional test failure.")

    bus.subscribe(broken_handler)

    bus.subscribe(
        lambda item: healthy_events.append(item)
    )

    errors = bus.publish(event)

    assert len(errors) == 1
    assert len(healthy_events) == 1

    print("✓ Subscriber failure isolation")

    # ------------------------------------------------------------------
    # Test 7: Unsubscribe
    # ------------------------------------------------------------------

    removed = bus.unsubscribe(subscription_id)

    assert removed is True

    removed_again = bus.unsubscribe(subscription_id)

    assert removed_again is False

    print("✓ Event unsubscribe")

    # ------------------------------------------------------------------
    # Test 8: Correlation
    # ------------------------------------------------------------------

    correlated = create_event(
        name=EventNames.AGENT_STARTED,
        category=EventCategory.AGENT,
        source="researcher",
        correlation_id="task_123",
        task_id="task_123",
        execution_id="exec_456",
        agent_id="agent_789",
    )

    assert correlated.correlation_id == "task_123"
    assert correlated.task_id == "task_123"
    assert correlated.execution_id == "exec_456"
    assert correlated.agent_id == "agent_789"

    print("✓ Event correlation")

    # ------------------------------------------------------------------
    # Test 9: Severity
    # ------------------------------------------------------------------

    error_event = create_event(
        name=EventNames.SYSTEM_ERROR,
        category=EventCategory.SYSTEM,
        source="test",
        severity=EventSeverity.ERROR,
        data={
            "error": "Test error",
        },
    )

    assert error_event.severity == EventSeverity.ERROR

    print("✓ Event severity")

    # ------------------------------------------------------------------
    # Test 10: Clear
    # ------------------------------------------------------------------

    bus.clear()

    assert bus.subscription_count() == 0

    print("✓ Event bus clear")

    print()
    print("=" * 60)
    print("EVENT DOMAIN MODEL TEST PASSED")
    print("=" * 60)


if __name__ == "__main__":
    run_tests()