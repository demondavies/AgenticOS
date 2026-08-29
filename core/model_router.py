"""
Phase 18: Model router — picks a light or default local Ollama model based
on task workspace and current VRAM headroom.

This codebase has no cloud model provider (see core/config.py — only
DEFAULT_MODEL, a local Ollama model, and an optional self-hosted
OpenAI-compatible endpoint for LM Studio/vLLM). Routing therefore chooses
between two local Ollama models rather than local-vs-cloud.

The VRAM probe talks to Ollama's native API directly, isolated to this one
function, the same way core.models.OllamaProvider isolates all other Ollama
specifics elsewhere in the codebase — VRAM headroom is Ollama-specific
infrastructure detail, not a concept the ModelProvider Protocol exposes.

Never blocks the caller and never raises: any failure falls back to the
default model.
"""
from __future__ import annotations

import logging

import requests

import core.config as config

log = logging.getLogger(__name__)

LIGHT_WORKSPACES = {"personal", "system"}
HEAVY_WORKSPACES = {"agency", "swarm", "development", "prospects", "outreach", "client"}


def ollama_free_vram_gb() -> float:
    """Best-effort estimate of free Ollama VRAM headroom, in GB.

    Returns 0.0 (i.e. "assume no headroom") on any error so routing always
    has a safe, conservative fallback instead of failing.
    """
    try:
        response = requests.get(f"{config.OLLAMA_HOST}/api/ps", timeout=2)
        if response.status_code != 200:
            return 0.0
        data = response.json()
        used_bytes = sum(
            model.get("size_vram", 0) for model in data.get("models", [])
        )
        used_gb = used_bytes / 1e9
        return max(0.0, 8.0 - used_gb)
    except Exception:
        return 0.0


def should_use_light_model(workspace: str) -> bool:
    """Return True if `workspace` should use the lighter local model."""
    if not config.OLLAMA_ENABLED or not config.AGENT_ROUTING_ENABLED:
        return False
    if workspace in HEAVY_WORKSPACES:
        return False
    if workspace not in LIGHT_WORKSPACES:
        return False
    return ollama_free_vram_gb() >= config.OLLAMA_VRAM_HEADROOM_GB


def get_model_for_workspace(workspace: str) -> tuple[str, str]:
    """Return (model_name, provider) for `workspace`.

    Provider is always "ollama" — this codebase has no cloud provider to
    fall back to (see module docstring).
    """
    if should_use_light_model(workspace):
        log.info(
            f"Routing workspace={workspace} -> light Ollama model "
            f"({config.OLLAMA_LIGHT_MODEL})"
        )
        return config.OLLAMA_LIGHT_MODEL, "ollama"

    log.info(
        f"Routing workspace={workspace} -> default Ollama model "
        f"({config.DEFAULT_MODEL})"
    )
    return config.DEFAULT_MODEL, "ollama"
