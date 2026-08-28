"""
ARNIE Agentic OS
Task Domain Model

This module defines the provider-independent Task contract.

IMPORTANT:
- This is the logical definition of a task.
- It does not yet own SQLite.
- It does not execute anything.
- It does not know about Ollama, agents, FastAPI, Discord, or the UI.

The Task Engine will eventually persist and execute these objects.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
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
# TASK STATUS
# ============================================================================


class TaskStatus(str, Enum):
    """
    Lifecycle states for an ARNIE task.
    """

    CREATED = "created"
    QUEUED = "queued"
    ASSIGNED = "assigned"
    RUNNING = "running"
    WAITING = "waiting"
    VERIFYING = "verifying"

    APPROVAL_REQUIRED = "approval_required"

    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    RETRYING = "retrying"


# ============================================================================
# TASK PRIORITY
# ============================================================================


class TaskPriority(str, Enum):
    """
    Priority levels.

    These are intentionally simple for now.
    The scheduler/queue can become more sophisticated later.
    """

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


# ============================================================================
# EXECUTION STATUS
# ============================================================================


class ExecutionStatus(str, Enum):
    """
    Status of an individual attempt to execute a task.
    """

    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ============================================================================
# TASK RESULT
# ============================================================================


@dataclass
class TaskResult:
    """
    Result produced by a task execution.

    A result can contain normal text as well as structured data.
    """

    success: bool

    output: Optional[str] = None

    data: Dict[str, Any] = field(default_factory=dict)

    error: Optional[str] = None

    artifact_ids: List[str] = field(default_factory=list)

    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# TASK
# ============================================================================


@dataclass
class Task:
    """
    The durable logical unit of work in ARNIE.

    A Task describes WHAT needs to happen.

    It does not describe HOW the work is performed.

    Execution, Agent, Model and Tool objects handle the HOW.
    """

    title: str
    description: str

    id: str = field(default_factory=lambda: new_id("task"))

    status: TaskStatus = TaskStatus.CREATED

    priority: TaskPriority = TaskPriority.NORMAL

    # Who/what created the task.
    creator: str = "user"

    # Agent assigned to perform the work.
    assigned_agent: Optional[str] = None

    # Workspace in which the task exists.
    #
    # Examples:
    #   personal
    #   agency
    #   media
    #   development
    #   client
    workspace: str = "personal"

    # Optional parent task for workflows/subtasks.
    parent_task_id: Optional[str] = None

    # Inputs supplied to the task.
    inputs: Dict[str, Any] = field(default_factory=dict)

    # Final result once the task completes.
    result: Optional[TaskResult] = None

    # Number of execution attempts.
    attempt_count: int = 0

    # Maximum automatic retries.
    max_retries: int = 2

    # Timestamps.
    created_at: datetime = field(default_factory=utc_now)

    started_at: Optional[datetime] = None

    completed_at: Optional[datetime] = None

    # Error information if the task fails.
    error: Optional[str] = None

    # Arbitrary metadata for future extensions.
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ---------------------------------------------------------------------
    # Lifecycle methods
    # ---------------------------------------------------------------------

    def queue(self) -> None:
        """Move the task into the queue."""
        self._require_status(
            {
                TaskStatus.CREATED,
                TaskStatus.RETRYING,
            }
        )

        self.status = TaskStatus.QUEUED

    def assign(self, agent_id: str) -> None:
        """Assign the task to an agent."""
        if not agent_id or not agent_id.strip():
            raise ValueError("agent_id cannot be empty.")

        self._require_status(
            {
                TaskStatus.QUEUED,
                TaskStatus.CREATED,
            }
        )

        self.assigned_agent = agent_id
        self.status = TaskStatus.ASSIGNED

    def start(self) -> None:
        """Start task execution."""
        self._require_status(
            {
                TaskStatus.ASSIGNED,
                TaskStatus.QUEUED,
                TaskStatus.RETRYING,
            }
        )

        self.status = TaskStatus.RUNNING

        if self.started_at is None:
            self.started_at = utc_now()

        self.attempt_count += 1

    def wait(self) -> None:
        """Pause execution while waiting for something external."""
        self._require_status(
            {
                TaskStatus.RUNNING,
            }
        )

        self.status = TaskStatus.WAITING

    def resume(self) -> None:
        """Resume a waiting task."""
        self._require_status(
            {
                TaskStatus.WAITING,
            }
        )

        self.status = TaskStatus.RUNNING

    def begin_verification(self) -> None:
        """Move a completed execution into verification."""
        self._require_status(
            {
                TaskStatus.RUNNING,
                TaskStatus.WAITING,
            }
        )

        self.status = TaskStatus.VERIFYING

    def require_approval(self) -> None:
        """Require human approval before completion."""
        self._require_status(
            {
                TaskStatus.VERIFYING,
            }
        )

        self.status = TaskStatus.APPROVAL_REQUIRED

    def approve(self) -> None:
        """Approve a task awaiting human approval."""
        self._require_status(
            {
                TaskStatus.APPROVAL_REQUIRED,
            }
        )

        self.complete()

    def reject(self, reason: Optional[str] = None) -> None:
        """Reject a task awaiting approval."""
        self._require_status(
            {
                TaskStatus.APPROVAL_REQUIRED,
                TaskStatus.VERIFYING,
            }
        )

        self.status = TaskStatus.REJECTED
        self.error = reason or "Task rejected."

        self.completed_at = utc_now()

    def complete(self, result: Optional[TaskResult] = None) -> None:
        """Mark the task as successfully completed."""
        self._require_status(
            {
                TaskStatus.RUNNING,
                TaskStatus.VERIFYING,
                TaskStatus.APPROVAL_REQUIRED,
            }
        )

        self.status = TaskStatus.COMPLETED
        self.result = result
        self.completed_at = utc_now()
        self.error = None

    def fail(
        self,
        error: str,
        retry: bool = False,
    ) -> None:
        """
        Mark the task as failed.

        If retry=True and retry attempts remain, the task enters RETRYING.
        Otherwise it becomes permanently FAILED.
        """

        if not error:
            error = "Unknown task failure."

        self.error = error

        if retry and self.can_retry():
            self.status = TaskStatus.RETRYING
        else:
            self.status = TaskStatus.FAILED
            self.completed_at = utc_now()

    def cancel(self, reason: Optional[str] = None) -> None:
        """Cancel the task."""
        self._require_status(
            {
                TaskStatus.CREATED,
                TaskStatus.QUEUED,
                TaskStatus.ASSIGNED,
                TaskStatus.RUNNING,
                TaskStatus.WAITING,
                TaskStatus.VERIFYING,
                TaskStatus.RETRYING,
            }
        )

        self.status = TaskStatus.CANCELLED

        if reason:
            self.error = reason

        self.completed_at = utc_now()

    # ---------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------

    def can_retry(self) -> bool:
        """
        Return True if another execution attempt is allowed.
        """
        return self.attempt_count < self.max_retries

    def is_terminal(self) -> bool:
        """
        Return True when no further normal lifecycle transitions are expected.
        """
        return self.status in {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.REJECTED,
        }

    def _require_status(
        self,
        allowed: set[TaskStatus],
    ) -> None:
        """
        Protect task lifecycle transitions from invalid state changes.
        """

        if self.status not in allowed:
            allowed_values = ", ".join(
                status.value for status in allowed
            )

            raise ValueError(
                f"Cannot transition task '{self.id}' "
                f"from '{self.status.value}'. "
                f"Allowed states: {allowed_values}"
            )

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the task into a JSON-friendly dictionary.
        """

        data = asdict(self)

        data["status"] = self.status.value
        data["priority"] = self.priority.value

        if self.result is not None:
            data["result"] = asdict(self.result)

        for key in (
            "created_at",
            "started_at",
            "completed_at",
        ):
            value = data.get(key)

            if isinstance(value, datetime):
                data[key] = value.isoformat()

        return data


# ============================================================================
# EXECUTION
# ============================================================================


@dataclass
class TaskExecution:
    """
    Records one attempt to execute a Task.

    A Task may have multiple executions because of retries.

    Task = WHAT needs doing.

    TaskExecution = WHAT HAPPENED during one attempt.
    """

    task_id: str

    id: str = field(default_factory=lambda: new_id("exec"))

    status: ExecutionStatus = ExecutionStatus.CREATED

    agent_id: Optional[str] = None

    model: Optional[str] = None

    provider: Optional[str] = None

    started_at: Optional[datetime] = None

    completed_at: Optional[datetime] = None

    result: Optional[TaskResult] = None

    error: Optional[str] = None

    metadata: Dict[str, Any] = field(default_factory=dict)

    def start(self) -> None:
        """Start this execution."""
        if self.status != ExecutionStatus.CREATED:
            raise ValueError(
                f"Execution '{self.id}' cannot start from "
                f"'{self.status.value}'."
            )

        self.status = ExecutionStatus.RUNNING
        self.started_at = utc_now()

    def complete(
        self,
        result: Optional[TaskResult] = None,
    ) -> None:
        """Complete this execution."""
        if self.status != ExecutionStatus.RUNNING:
            raise ValueError(
                f"Execution '{self.id}' cannot complete from "
                f"'{self.status.value}'."
            )

        self.status = ExecutionStatus.COMPLETED
        self.result = result
        self.completed_at = utc_now()

    def fail(self, error: str) -> None:
        """Fail this execution."""
        if self.status != ExecutionStatus.RUNNING:
            raise ValueError(
                f"Execution '{self.id}' cannot fail from "
                f"'{self.status.value}'."
            )

        self.status = ExecutionStatus.FAILED
        self.error = error or "Unknown execution failure."
        self.completed_at = utc_now()

    def cancel(self, reason: Optional[str] = None) -> None:
        """Cancel this execution."""
        if self.status not in {
            ExecutionStatus.CREATED,
            ExecutionStatus.RUNNING,
        }:
            raise ValueError(
                f"Execution '{self.id}' cannot be cancelled from "
                f"'{self.status.value}'."
            )

        self.status = ExecutionStatus.CANCELLED

        if reason:
            self.error = reason

        self.completed_at = utc_now()

    def to_dict(self) -> Dict[str, Any]:
        """Convert execution to a JSON-friendly dictionary."""
        data = asdict(self)

        data["status"] = self.status.value

        if self.result is not None:
            data["result"] = asdict(self.result)

        for key in (
            "started_at",
            "completed_at",
        ):
            value = data.get(key)

            if isinstance(value, datetime):
                data[key] = value.isoformat()

        return data


# ============================================================================
# DEVELOPMENT TESTS
# ============================================================================


def run_tests() -> None:
    """
    Small dependency-free test suite.

    This tests the domain model without touching:
        - Ollama
        - SQLite
        - FastAPI
        - Discord
        - existing ARNIE code
    """

    print("=" * 60)
    print("ARNIE TASK DOMAIN MODEL TEST")
    print("=" * 60)

    # ------------------------------------------------------------------
    # Test 1: Creation
    # ------------------------------------------------------------------

    task = Task(
        title="Test research task",
        description="Verify the ARNIE Task lifecycle.",
        workspace="development",
    )

    assert task.status == TaskStatus.CREATED
    assert task.id.startswith("task_")

    print("✓ Task creation")

    # ------------------------------------------------------------------
    # Test 2: Queue
    # ------------------------------------------------------------------

    task.queue()

    assert task.status == TaskStatus.QUEUED

    print("✓ Task queue")

    # ------------------------------------------------------------------
    # Test 3: Assignment
    # ------------------------------------------------------------------

    task.assign("researcher")

    assert task.status == TaskStatus.ASSIGNED
    assert task.assigned_agent == "researcher"

    print("✓ Agent assignment")

    # ------------------------------------------------------------------
    # Test 4: Start
    # ------------------------------------------------------------------

    task.start()

    assert task.status == TaskStatus.RUNNING
    assert task.attempt_count == 1
    assert task.started_at is not None

    print("✓ Task start")

    # ------------------------------------------------------------------
    # Test 5: Verification
    # ------------------------------------------------------------------

    task.begin_verification()

    assert task.status == TaskStatus.VERIFYING

    print("✓ Verification state")

    # ------------------------------------------------------------------
    # Test 6: Completion
    # ------------------------------------------------------------------

    result = TaskResult(
        success=True,
        output="Task completed successfully.",
    )

    task.complete(result)

    assert task.status == TaskStatus.COMPLETED
    assert task.result is not None
    assert task.result.success is True
    assert task.completed_at is not None
    assert task.is_terminal() is True

    print("✓ Task completion")

    # ------------------------------------------------------------------
    # Test 7: Serialization
    # ------------------------------------------------------------------

    data = task.to_dict()

    assert isinstance(data, dict)
    assert data["status"] == "completed"
    assert data["workspace"] == "development"

    print("✓ Task serialization")

    # ------------------------------------------------------------------
    # Test 8: Execution
    # ------------------------------------------------------------------

    execution = TaskExecution(
        task_id=task.id,
        agent_id="researcher",
        model="hermes3:8b",
        provider="ollama",
    )

    execution.start()

    assert execution.status == ExecutionStatus.RUNNING

    execution.complete(
        TaskResult(
            success=True,
            output="Execution succeeded.",
        )
    )

    assert execution.status == ExecutionStatus.COMPLETED
    assert execution.completed_at is not None

    print("✓ Task execution")

    # ------------------------------------------------------------------
    # Test 9: Retry logic
    # ------------------------------------------------------------------

    retry_task = Task(
        title="Retry test",
        description="Test retry lifecycle.",
        max_retries=2,
    )

    retry_task.queue()
    retry_task.assign("researcher")
    retry_task.start()

    assert retry_task.attempt_count == 1

    retry_task.fail(
        "Temporary test failure.",
        retry=True,
    )

    assert retry_task.status == TaskStatus.RETRYING
    assert retry_task.can_retry() is True

    print("✓ Retry lifecycle")

    # ------------------------------------------------------------------
    # Test 10: Cancellation
    # ------------------------------------------------------------------

    cancel_task = Task(
        title="Cancellation test",
        description="Test cancellation.",
    )

    cancel_task.queue()

    cancel_task.cancel("User cancelled test.")

    assert cancel_task.status == TaskStatus.CANCELLED
    assert cancel_task.is_terminal() is True

    print("✓ Cancellation")

    print()
    print("=" * 60)
    print("TASK DOMAIN MODEL TEST PASSED")
    print("=" * 60)


if __name__ == "__main__":
    run_tests()