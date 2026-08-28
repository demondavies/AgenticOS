"""
ARNIE Agentic OS
Model Abstraction Layer

This module defines the contracts between the Agentic OS harness and
the underlying AI model runtime.

IMPORTANT:
- The harness should not depend directly on Ollama.
- Ollama is a provider implementation.
- Models are selected by capability/configuration.
- Future providers can be added without rewriting the harness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Protocol


# ============================================================================
# CAPABILITY CONTRACTS
# ============================================================================

CAPABILITY_SYSTEM_PROMPTS: Dict[str, str] = {
    "tool_synthesis": (
        "You are ARNIE's tool-synthesis engine.\n\n"
        "A runtime tool has already executed successfully and supplied "
        "authoritative evidence. Your job is to answer the user's request "
        "using that evidence.\n\n"
        "Rules:\n"
        "1. Treat runtime tool evidence as the current factual source.\n"
        "2. Never claim you lack access to information that the tool just "
        "retrieved.\n"
        "3. Never substitute your training knowledge or knowledge cutoff "
        "for retrieved evidence.\n"
        "4. Never invent facts, dates, versions, sources, or results.\n"
        "5. If the evidence is insufficient, say what is missing instead "
        "of guessing.\n"
        "6. Do not emit tool calls. The tool has already executed.\n"
        "7. For web results, identify the relevant source/title when useful.\n"
        "8. Keep the final answer concise and directly answer the user."
    ),
}


def capability_system_prompt(capability: str) -> Optional[str]:
    """Return the system contract for a model capability, if one exists."""
    return CAPABILITY_SYSTEM_PROMPTS.get(
        (capability or "conversation").strip().lower()
    )


def prepare_capability_messages(
    messages: List["ModelMessage"],
    capability: str,
) -> List["ModelMessage"]:
    """
    Apply the provider-independent capability contract.

    For tool_synthesis we deliberately remove legacy conversational system
    prompts. Those prompts belong to the old monolithic agent loop and can
    contradict live tool evidence (for example, stale knowledge-cutoff
    instructions).

    A system message containing an authoritative tool result is preserved as
    a tool message so the evidence remains available to the model.
    """
    capability_key = (capability or "conversation").strip().lower()
    contract = capability_system_prompt(capability_key)

    if not contract:
        return list(messages)

    prepared: List["ModelMessage"] = [
        ModelMessage(role="system", content=contract)
    ]

    for message in messages:
        if message.role == "system":
            if "AUTHORITATIVE TOOL RESULT" in message.content.upper():
                prepared.append(
                    ModelMessage(
                        role="user",
                        content=(
                            "RUNTIME TOOL EVIDENCE — AUTHORITATIVE\n"
                            "========================================\n"
                            f"{message.content}\n\n"
                            "Use this evidence to answer the original request."
                        ),
                        name=message.name or "runtime_tool",
                    )
                )
            continue

        prepared.append(message)

    return prepared


# ============================================================================
# DATA CONTRACTS
# ============================================================================


@dataclass
class ModelMessage:
    """
    A single message sent to a model.

    role:
        system, user, assistant, or tool

    content:
        Human-readable message content.

    name:
        Optional name identifying the message source.
    """

    role: str
    content: str
    name: Optional[str] = None


@dataclass
class ModelRequest:
    """
    A provider-independent request for model inference.

    The harness uses this object instead of constructing provider-specific
    requests directly.
    """

    messages: List[ModelMessage]

    # Capability is more important than a specific model name.
    #
    # Examples:
    #   conversation
    #   reasoning
    #   coding
    #   research
    #   summarization
    capability: str = "conversation"

    # Optional explicit model override.
    #
    # This is useful during development/testing, but normal application
    # logic should prefer capability-based selection.
    model: Optional[str] = None

    temperature: Optional[float] = None
    max_tokens: Optional[int] = None

    # Provider-specific options may be passed without contaminating the
    # core architecture with provider-specific fields.
    options: Dict[str, Any] = field(default_factory=dict)

    # Metadata allows the harness to attach useful tracing information.
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelResponse:
    """
    Provider-independent model response.
    """

    content: str

    model: str = ""
    provider: str = ""

    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # Optional usage information.
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None

    # Provider-specific raw data can be retained for debugging without
    # forcing the harness to understand it.
    raw: Any = None

    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelStreamChunk:
    """
    A single streaming response chunk.
    """

    content: str

    model: str = ""
    provider: str = ""

    done: bool = False

    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelInfo:
    """
    Describes a model available through a provider.
    """

    name: str
    provider: str

    capabilities: List[str] = field(default_factory=list)

    context_length: Optional[int] = None

    # Optional metadata such as parameter count, quantization, etc.
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# PROVIDER CONTRACT
# ============================================================================


class ModelProvider(Protocol):
    """
    Interface implemented by model runtimes/providers.

    The Agentic OS talks to this interface.

    It does NOT need to know whether the provider is:
        - Ollama
        - OmniRoute
        - an OpenAI-compatible endpoint
        - another local runtime
        - a future runtime we haven't discovered yet
    """

    @property
    def name(self) -> str:
        """Return the provider's human-readable name."""
        ...

    def chat(self, request: ModelRequest) -> ModelResponse:
        """Execute a normal model request."""
        ...

    def stream(self, request: ModelRequest) -> Iterable[ModelStreamChunk]:
        """Execute a streaming model request."""
        ...

    def list_models(self) -> List[ModelInfo]:
        """Return models available through this provider."""
        ...

    def health_check(self) -> bool:
        """Return True if the provider is currently available."""
        ...


# ============================================================================
# MODEL REGISTRY
# ============================================================================


class ModelRegistry:
    """
    Registry of available model providers.

    The registry is deliberately small at this stage.

    Later this becomes the basis for model routing and capability matching.
    """

    def __init__(self) -> None:
        self._providers: Dict[str, ModelProvider] = {}

    def register(self, provider: ModelProvider) -> None:
        """
        Register a model provider.

        Provider names must be unique.
        """
        provider_name = provider.name.strip().lower()

        if not provider_name:
            raise ValueError("Model provider must have a name.")

        self._providers[provider_name] = provider

    def get(self, provider_name: str) -> ModelProvider:
        """
        Retrieve a registered provider.
        """
        key = provider_name.strip().lower()

        if key not in self._providers:
            raise KeyError(
                f"Model provider '{provider_name}' is not registered."
            )

        return self._providers[key]

    def list_providers(self) -> List[str]:
        """
        Return registered provider names.
        """
        return sorted(self._providers.keys())

    def list_models(self) -> List[ModelInfo]:
        """
        Return all models exposed by all registered providers.
        """
        models: List[ModelInfo] = []

        for provider in self._providers.values():
            try:
                models.extend(provider.list_models())
            except Exception:
                # One unavailable provider should not prevent the registry
                # from reporting models from other providers.
                continue

        return models


# ============================================================================
# OLLAMA PROVIDER
# ============================================================================


class OllamaProvider:
    """
    Ollama implementation of the ModelProvider interface.

    Ollama is intentionally isolated to this class.

    If we replace Ollama later, the rest of the Agentic OS should not need
    to know that anything changed.
    """

    def __init__(
        self,
        host: str = "http://127.0.0.1:11434",
        default_model: str = "hermes3:8b",
    ) -> None:
        self.host = host.rstrip("/")
        self.default_model = default_model

        try:
            import ollama  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "The 'ollama' Python package is not installed. "
                "Install it with: pip install ollama"
            ) from exc

        self._client = ollama.Client(host=self.host)

    @property
    def name(self) -> str:
        return "ollama"

    def chat(self, request: ModelRequest) -> ModelResponse:
        """
        Execute a non-streaming Ollama request.
        """

        model_name = request.model or self.default_model

        prepared_messages = prepare_capability_messages(
            request.messages,
            request.capability,
        )

        messages: List[Dict[str, str]] = []

        for message in prepared_messages:
            item: Dict[str, str] = {
                "role": message.role,
                "content": message.content,
            }

            if message.name:
                item["name"] = message.name

            messages.append(item)

        kwargs: Dict[str, Any] = {
            "model": model_name,
            "messages": messages,
        }

        options: Dict[str, Any] = dict(request.options)

        if request.temperature is not None:
            options["temperature"] = request.temperature

        if request.max_tokens is not None:
            options["num_predict"] = request.max_tokens

        if options:
            kwargs["options"] = options

        response = self._client.chat(**kwargs)

        # Ollama's Python response object behaves like a dictionary in
        # current versions, but we deliberately keep extraction defensive.
        content = ""

        try:
            content = response["message"]["content"]
        except Exception:
            try:
                content = response.message.content
            except Exception:
                content = str(response)

        returned_model = model_name

        try:
            returned_model = response.get("model", model_name)
        except Exception:
            pass

        prompt_tokens = None
        completion_tokens = None
        total_tokens = None

        try:
            prompt_tokens = response.get("prompt_eval_count")
            completion_tokens = response.get("eval_count")

            if prompt_tokens is not None and completion_tokens is not None:
                total_tokens = prompt_tokens + completion_tokens
        except Exception:
            pass

        return ModelResponse(
            content=content,
            model=returned_model,
            provider=self.name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            raw=response,
            metadata={
                "capability": request.capability,
                "request_metadata": request.metadata,
            },
        )

    def stream(
        self,
        request: ModelRequest,
    ) -> Iterable[ModelStreamChunk]:
        """
        Execute a streaming Ollama request.
        """

        model_name = request.model or self.default_model

        prepared_messages = prepare_capability_messages(
            request.messages,
            request.capability,
        )

        messages: List[Dict[str, str]] = []

        for message in prepared_messages:
            item: Dict[str, str] = {
                "role": message.role,
                "content": message.content,
            }

            if message.name:
                item["name"] = message.name

            messages.append(item)

        kwargs: Dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "stream": True,
        }

        options: Dict[str, Any] = dict(request.options)

        if request.temperature is not None:
            options["temperature"] = request.temperature

        if request.max_tokens is not None:
            options["num_predict"] = request.max_tokens

        if options:
            kwargs["options"] = options

        response_stream = self._client.chat(**kwargs)

        for chunk in response_stream:
            content = ""

            try:
                content = chunk["message"]["content"]
            except Exception:
                try:
                    content = chunk.message.content
                except Exception:
                    content = ""

            done = False

            try:
                done = bool(chunk.get("done", False))
            except Exception:
                pass

            yield ModelStreamChunk(
                content=content,
                model=model_name,
                provider=self.name,
                done=done,
                metadata={
                    "capability": request.capability,
                    "request_metadata": request.metadata,
                },
            )

    def list_models(self) -> List[ModelInfo]:
        """
        Ask Ollama for its currently available local models.
        """

        response = self._client.list()

        models: List[ModelInfo] = []

        try:
            raw_models = response["models"]
        except Exception:
            try:
                raw_models = response.models
            except Exception:
                raw_models = []

        for item in raw_models:
            if isinstance(item, dict):
                name = item.get("name") or item.get("model") or ""
                metadata = item
            else:
                name = getattr(item, "model", "") or getattr(
                    item, "name", ""
                )
                metadata = {}

            if not name:
                continue

            models.append(
                ModelInfo(
                    name=name,
                    provider=self.name,
                    capabilities=[],
                    metadata=metadata,
                )
            )

        return models

    def health_check(self) -> bool:
        """
        Check whether the Ollama service is reachable.
        """

        try:
            self._client.list()
            return True
        except Exception:
            return False


# ============================================================================
# OPENAI-COMPATIBLE PROVIDER
# ============================================================================


class OpenAICompatibleProvider:
    """
    ModelProvider implementation for any OpenAI-API-compatible inference
    server (LM Studio, vLLM, and similar local runtimes).

    The provider's identity (`name`) is configurable rather than hardcoded,
    since this same class backs multiple distinct providers depending on
    which server it is pointed at.
    """

    def __init__(
        self,
        base_url: str,
        default_model: str,
        provider_name: str,
        api_key: str = "not-needed",
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.api_key = api_key
        self.timeout = timeout
        self._provider_name = provider_name.strip().lower()

        if not self._provider_name:
            raise ValueError("OpenAICompatibleProvider requires a provider_name.")

        import requests  # type: ignore

        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
        )

    @property
    def name(self) -> str:
        return self._provider_name

    def _build_payload(self, request: ModelRequest) -> Dict[str, Any]:
        model_name = request.model or self.default_model

        prepared_messages = prepare_capability_messages(
            request.messages,
            request.capability,
        )

        messages: List[Dict[str, str]] = []

        for message in prepared_messages:
            item: Dict[str, str] = {
                "role": message.role,
                "content": message.content,
            }

            if message.name:
                item["name"] = message.name

            messages.append(item)

        payload: Dict[str, Any] = dict(request.options)
        payload["model"] = model_name
        payload["messages"] = messages

        if request.temperature is not None:
            payload["temperature"] = request.temperature

        if request.max_tokens is not None:
            payload["max_tokens"] = request.max_tokens

        return payload

    def chat(self, request: ModelRequest) -> ModelResponse:
        """
        Execute a non-streaming chat completion request.
        """

        payload = self._build_payload(request)

        response = self._session.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()

        data = response.json()

        content = ""
        returned_model = payload["model"]

        try:
            content = data["choices"][0]["message"]["content"]
        except Exception:
            content = str(data)

        try:
            returned_model = data.get("model", returned_model)
        except Exception:
            pass

        prompt_tokens = None
        completion_tokens = None
        total_tokens = None

        try:
            usage = data.get("usage") or {}
            prompt_tokens = usage.get("prompt_tokens")
            completion_tokens = usage.get("completion_tokens")
            total_tokens = usage.get("total_tokens")
        except Exception:
            pass

        return ModelResponse(
            content=content,
            model=returned_model,
            provider=self.name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            raw=data,
            metadata={
                "capability": request.capability,
                "request_metadata": request.metadata,
            },
        )

    def stream(
        self,
        request: ModelRequest,
    ) -> Iterable[ModelStreamChunk]:
        """
        Execute a streaming chat completion request over server-sent events.
        """

        import json

        payload = self._build_payload(request)
        payload["stream"] = True

        response = self._session.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            timeout=self.timeout,
            stream=True,
        )
        response.raise_for_status()

        model_name = payload["model"]

        for line in response.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue

            data_str = line[len("data:"):].strip()

            if data_str == "[DONE]":
                yield ModelStreamChunk(
                    content="",
                    model=model_name,
                    provider=self.name,
                    done=True,
                    metadata={
                        "capability": request.capability,
                        "request_metadata": request.metadata,
                    },
                )
                break

            try:
                chunk_data = json.loads(data_str)
            except Exception:
                continue

            content = ""

            try:
                content = chunk_data["choices"][0]["delta"].get("content", "")
            except Exception:
                content = ""

            yield ModelStreamChunk(
                content=content,
                model=chunk_data.get("model", model_name),
                provider=self.name,
                done=False,
                metadata={
                    "capability": request.capability,
                    "request_metadata": request.metadata,
                },
            )

    def list_models(self) -> List[ModelInfo]:
        """
        Ask the server for its currently available models.
        """

        response = self._session.get(
            f"{self.base_url}/models",
            timeout=self.timeout,
        )
        response.raise_for_status()

        data = response.json()

        models: List[ModelInfo] = []

        for item in data.get("data", []):
            name = item.get("id") or item.get("name") or ""

            if not name:
                continue

            models.append(
                ModelInfo(
                    name=name,
                    provider=self.name,
                    capabilities=[],
                    metadata=item,
                )
            )

        return models

    def health_check(self) -> bool:
        """
        Check whether the server is reachable.
        """

        try:
            response = self._session.get(
                f"{self.base_url}/models",
                timeout=self.timeout,
            )
            return response.ok
        except Exception:
            return False


# ============================================================================
# DEFAULT REGISTRY
# ============================================================================


def create_default_model_registry() -> ModelRegistry:
    """
    Create the initial ARNIE model registry.

    Ollama is always registered. A second OpenAI-compatible provider
    (LM Studio, vLLM, etc.) is registered when enabled via config, so
    agents can be routed to either provider by name without any
    provider-name string appearing in the harness.
    """

    registry = ModelRegistry()

    registry.register(
        OllamaProvider(
            host="http://127.0.0.1:11434",
            default_model="hermes3:8b",
        )
    )

    try:
        from core import config as _config

        if getattr(_config, "OPENAI_COMPAT_ENABLED", False):
            registry.register(
                OpenAICompatibleProvider(
                    base_url=_config.OPENAI_COMPAT_HOST,
                    default_model=_config.OPENAI_COMPAT_MODEL,
                    provider_name=_config.OPENAI_COMPAT_PROVIDER_NAME,
                    api_key=_config.OPENAI_COMPAT_API_KEY,
                )
            )
    except Exception:
        # A misconfigured or unreachable second provider must not prevent
        # the registry from returning a working Ollama-backed registry.
        pass

    return registry


# ============================================================================
# DEVELOPMENT TEST
# ============================================================================


if __name__ == "__main__":
    """
    Safe standalone diagnostic.

    This does NOT send a prompt to a model.

    It only checks whether Ollama is reachable and lists the models it knows
    about.
    """

    print("=" * 60)
    print("ARNIE MODEL ABSTRACTION TEST")
    print("=" * 60)

    try:
        registry = create_default_model_registry()

        print("\nProviders:")
        for provider in registry.list_providers():
            print(f"  ✓ {provider}")

        print("\nChecking Ollama...")

        ollama = registry.get("ollama")

        if ollama.health_check():
            print("  ✓ Ollama is reachable")
        else:
            print("  ✗ Ollama is not reachable")
            raise SystemExit(1)

        print("\nAvailable models:")

        models = ollama.list_models()

        if not models:
            print("  (none found)")
        else:
            for model in models:
                print(f"  ✓ {model.name}")

        print("\nModel abstraction test PASSED.")
        print("=" * 60)

    except Exception as exc:
        print("\nMODEL ABSTRACTION TEST FAILED")
        print(f"Reason: {exc}")
        print("=" * 60)
        raise