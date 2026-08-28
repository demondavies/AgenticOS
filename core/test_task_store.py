"""Regression tests for the SQLite-backed Task store."""

from __future__ import annotations

import os
import tempfile

from capabilities.tasks import TaskStore
from core.tasks import Task, TaskStatus


def run_tests() -> None:
    print("=" * 60)
    print("ARNIE TASK STORE TEST")
    print("=" * 60)

    tmp_dir = tempfile.mkdtemp(prefix="agenticos_task_store_")
    db_path = os.path.join(tmp_dir, "tasks.db")

    store = TaskStore(db_path=db_path)
    store.init_db()

    print("✓ TaskStore init_db")

    task = Task(
        title="Test tool request",
        description="Verify Task persistence.",
        workspace="development",
    )
    task.queue()
    task.assign("coordinator")
    task.start()

    store.save_task(task)

    print("✓ save_task")

    fetched = store.get_task(task.id)

    assert fetched is not None
    assert fetched["title"] == "Test tool request"
    assert fetched["workspace"] == "development"
    assert fetched["status"] == TaskStatus.RUNNING.value
    assert fetched["assigned_agent"] == "coordinator"

    print("✓ get_task round-trip")

    task.complete()
    store.save_task(task)

    fetched_again = store.get_task(task.id)
    assert fetched_again["status"] == TaskStatus.COMPLETED.value

    print("✓ save_task upserts by id")

    listed = store.list_tasks(workspace="development")
    assert any(row["id"] == task.id for row in listed)

    print("✓ list_tasks")

    print()
    print("=" * 60)
    print("TASK STORE TEST PASSED")
    print("=" * 60)


if __name__ == "__main__":
    run_tests()
