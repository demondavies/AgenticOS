"""
Phase 19: Client project tracking service.
Stores active agency clients in clients.json at the project root.
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

CLIENTS_FILE = Path(os.environ.get("CLIENTS_FILE", "clients.json"))


@dataclass
class Client:
    id: str
    name: str
    service: str
    status: str          # active / paused / completed / prospect
    created_at: str
    notes: str = ""


def _load() -> list[Client]:
    if not CLIENTS_FILE.exists():
        return []
    with open(CLIENTS_FILE, "r", encoding="utf-8") as f:
        return [Client(**c) for c in json.load(f)]


def _save(clients: list[Client]) -> None:
    with open(CLIENTS_FILE, "w", encoding="utf-8") as f:
        json.dump([asdict(c) for c in clients], f, indent=2)


def add_client(name: str, service: str, notes: str = "") -> Client:
    clients = _load()
    client_id = f"client_{int(datetime.now(timezone.utc).timestamp())}"
    client = Client(
        id=client_id,
        name=name,
        service=service,
        status="prospect",
        created_at=datetime.now(timezone.utc).isoformat(),
        notes=notes,
    )
    clients.append(client)
    _save(clients)
    return client


def list_clients(status: str | None = None) -> list[Client]:
    clients = _load()
    if status:
        clients = [c for c in clients if c.status == status]
    return clients


def update_client_status(client_id: str, status: str, notes: str = "") -> Client | None:
    clients = _load()
    for c in clients:
        if c.id == client_id:
            c.status = status
            if notes:
                c.notes = notes
            _save(clients)
            return c
    return None
