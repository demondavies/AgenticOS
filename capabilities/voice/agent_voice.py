"""AgenticOS voice-agent orchestration.

Owns voice conversation routing between Intent, Harness, Tools, Model, and Oak.
No Discord or FastAPI dependency.
"""

from __future__ import annotations

import asyncio
import re
import threading
from typing import Any, Awaitable, Callable, Dict, Optional

from .oak import clean_text_for_speech, speak_text_kokoro


ToolExecutor = Callable[..., Awaitable[Any]]


class VoiceAgent:
    """Canonical conversational voice orchestration boundary."""

    def __init__(
        self,
        *,
        harness,
        intent_router,
        tool_registry,
        tool_executor: ToolExecutor,
        channel_id: str,
        base_system_prompt: str,
        owner_extensions: str = "",
        model: str = "hermes3:8b",
    ) -> None:
        self.harness = harness
        self.intent_router = intent_router
        self.tool_registry = tool_registry
        self.tool_executor = tool_executor
        self.channel_id = channel_id
        self.base_system_prompt = base_system_prompt
        self.owner_extensions = owner_extensions
        self.model = model

    @staticmethod
    def _extract_tool_call(text: str) -> Optional[Dict[str, Any]]:
        match = (
            re.search(r"<tool_call>(.*?)</tool_call>", text, re.DOTALL)
            or re.search(
                r'(\{\s*"name"\s*:\s*".*?"\s*,\s*"arguments"\s*:\s*\{.*?\}\s*\})',
                text,
                re.DOTALL,
            )
        )
        if not match:
            return None

        try:
            import json

            return json.loads(match.group(1).strip())
        except Exception:
            return None

    @staticmethod
    def _clean_model_text(text: str) -> str:
        return re.sub(
            r"<tool_call>.*?</tool_call>",
            "",
            str(text or ""),
            flags=re.DOTALL,
        ).strip()

    def _stream_model_sync(self, messages):
        """Yield canonical AgenticOS ModelStreamChunk objects."""
        return self.harness.stream(
            messages,
            model=self.model,
            capability="conversation",
        )

    async def _run_model_stream(self, messages):
        """Bridge the synchronous provider stream into the async voice loop."""
        queue: asyncio.Queue = asyncio.Queue()
        finished = object()
        loop = asyncio.get_running_loop()

        def producer() -> None:
            try:
                for chunk in self._stream_model_sync(messages):
                    asyncio.run_coroutine_threadsafe(queue.put(chunk), loop)
            except Exception as exc:
                asyncio.run_coroutine_threadsafe(queue.put(exc), loop)
            finally:
                asyncio.run_coroutine_threadsafe(queue.put(finished), loop)

        threading.Thread(target=producer, daemon=True).start()

        while True:
            item = await queue.get()

            if item is finished:
                break

            if isinstance(item, Exception):
                raise item

            # AgenticOS owns the provider abstraction. VoiceAgent consumes the
            # canonical ModelStreamChunk contract rather than provider internals.
            content = getattr(item, "content", None)
            if content is None and isinstance(item, dict):
                content = item.get("content", "")

            if content:
                yield str(content)

    async def stream(self, clean_content: str, is_owner: bool = True):
        """Stream a complete voice interaction as normalized voice events."""
        history = self.harness.get_memory(self.channel_id)

        if not history:
            full_prompt = self.base_system_prompt + (
                self.owner_extensions if is_owner else ""
            )
            history.append({"role": "system", "content": full_prompt})

        self.harness.save_memory(
            self.channel_id,
            "local_owner_voice",
            "user",
            clean_content,
        )
        history.append({"role": "user", "content": clean_content})

        voice_intent = self.intent_router.route(
            clean_content,
            is_owner=is_owner,
        )

        print(
            f"🧭 [Voice Intent Router] input={clean_content!r} "
            f"tool={voice_intent.tool_name!r} args={voice_intent.arguments!r}"
        )

        voice_tool_name = voice_intent.tool_name
        voice_tool_args = dict(voice_intent.arguments)

        if voice_tool_name:
            try:
                print(
                    f"🛠️ [Voice Action] Deterministic Wave-1 Tool: "
                    f"{voice_tool_name}"
                )

                tool_output = await self.tool_executor(
                    voice_tool_name,
                    voice_tool_args,
                    source="bot.voice_intent",
                )

                if self.harness.tool_execution_mode(voice_tool_name) == "direct":
                    final_text = str(tool_output)
                else:
                    synthesis_prompt = (
                        "TOOL RESULT — AUTHORITATIVE EVIDENCE\n"
                        "====================================\n"
                        f"Tool: {voice_tool_name}\n\n"
                        f"{tool_output}\n\n"
                        "SYNTHESIS RULES:\n"
                        "1. Answer the user's request using the tool result above.\n"
                        "2. Treat the tool result as the current factual source.\n"
                        "3. Do not claim you lack access to information that this "
                        "tool has just retrieved.\n"
                        "4. Do not replace retrieved facts with your training "
                        "knowledge or knowledge cutoff.\n"
                        "5. Do not invent facts, dates, versions, or sources.\n"
                        "6. If the tool result is insufficient, say exactly what "
                        "is missing rather than guessing.\n"
                        "7. For web results, identify the relevant source/title "
                        "when useful.\n"
                    )

                    history.append(
                        {
                            "role": "system",
                            "content": synthesis_prompt,
                        }
                    )

                    final_text = await self.harness.chat(
                        history,
                        model=self.model,
                        capability="tool_synthesis",
                    )
                    final_text = self._clean_model_text(final_text)

                    if not final_text:
                        final_text = str(tool_output)

                self.harness.save_memory(
                    self.channel_id,
                    "local_owner_voice",
                    "assistant",
                    final_text,
                )

                yield {"type": "done", "text": final_text}
                return

            except Exception as err:
                print(
                    f"❌ [Voice Tool Routing Error] "
                    f"[{voice_tool_name}]: {err}"
                )
                raise

        lower = clean_content.lower()

        if (
            (
                is_owner
                and any(
                    k in lower
                    for k in [
                        "cpu",
                        "ram",
                        "memory",
                        "hardware",
                        "system status",
                        "telemetry",
                        "metrics",
                    ]
                )
            )
            or re.match(
                r"^\s*(?:launch|run|deploy)\s+swarm:\s*(.+)$",
                clean_content,
                re.I,
            )
            or re.match(
                r"^\s*(?:open|launch|start|run)\s+"
                r"(?:app|program|software)?\s*(.+)$",
                clean_content,
                re.I,
            )
        ):
            reply = await self.tool_executor(
                "__legacy_voice_agent_logic__",
                {
                    "channel_id": self.channel_id,
                    "user_id": "local_owner_voice",
                    "content": clean_content,
                    "is_owner": is_owner,
                },
                source="voice",
            )
            yield {"type": "reply", "text": str(reply)}
            return

        first_text = ""

        async for token in self._run_model_stream(history):
            first_text += token
            yield {"type": "token", "text": token}

        tool_data = self._extract_tool_call(first_text)

        if tool_data:
            tool_output = await self.tool_executor(
                tool_data.get("name"),
                tool_data.get("arguments", {}) or {},
                source="voice",
            )

            history.append(
                {
                    "role": "assistant",
                    "content": first_text,
                }
            )
            history.append(
                {
                    "role": "system",
                    "content": (
                        f"Tool output received:\n\n{tool_output}\n\n"
                        "Please generate your final response."
                    ),
                }
            )

            final_text = ""

            async for token in self._run_model_stream(history):
                final_text += token
                yield {"type": "token", "text": token}

            final_text = self._clean_model_text(final_text)

            if not final_text:
                final_text = str(tool_output)

            self.harness.save_memory(
                self.channel_id,
                "local_owner_voice",
                "assistant",
                final_text,
            )
            yield {"type": "done", "text": final_text}
            return

        clean_reply = self._clean_model_text(first_text)

        if not clean_reply:
            clean_reply = (
                "I didn't receive a response from the model. "
                "Please try that again."
            )

        self.harness.save_memory(
            self.channel_id,
            "local_owner_voice",
            "assistant",
            clean_reply,
        )
        yield {"type": "done", "text": clean_reply}


class VoiceService:
    """Stable Harness-facing voice service and spoken-response adapter."""

    def __init__(self, engine=None) -> None:
        from .service import get_voice_engine

        self.engine = engine or get_voice_engine()
        self._agent: Optional[VoiceAgent] = None

    def record(self) -> bytes:
        return self.engine.record_audio_until_silence()

    def transcribe(self, audio_bytes: bytes) -> str:
        return self.engine.transcribe_audio_bytes(audio_bytes)

    def configure_agent(
        self,
        *,
        harness,
        intent_router,
        tool_registry,
        tool_executor: ToolExecutor,
        channel_id: str,
        base_system_prompt: str,
        owner_extensions: str = "",
        model: str = "hermes3:8b",
    ) -> VoiceAgent:
        self._agent = VoiceAgent(
            harness=harness,
            intent_router=intent_router,
            tool_registry=tool_registry,
            tool_executor=tool_executor,
            channel_id=channel_id,
            base_system_prompt=base_system_prompt,
            owner_extensions=owner_extensions,
            model=model,
        )
        return self._agent

    @property
    def agent(self) -> VoiceAgent:
        if self._agent is None:
            raise RuntimeError(
                "VoiceService agent is not configured. "
                "Call configure_agent() during AgenticOS startup."
            )
        return self._agent

    @staticmethod
    def _split_speech_sentences(buffer: str):
        chunks = []

        while True:
            match = re.search(
                r"(.+?[.!?](?:['\"”’)]*)?)(?:\s+|$)",
                buffer,
                re.S,
            )
            if not match:
                break

            candidate = match.group(1).strip()
            if candidate:
                chunks.append(candidate)

            buffer = buffer[match.end():]

        if len(buffer) > 260:
            cut = max(
                buffer.rfind(", ", 0, 260),
                buffer.rfind("; ", 0, 260),
            )
            if cut > 100:
                chunks.append(buffer[:cut].strip())
                buffer = buffer[cut + 1:].lstrip()

        return chunks, buffer

    async def stream(self, clean_content: str, is_owner: bool = True):
        """Stream AgenticOS voice events and speak them through canonical Oak."""
        speech_queue: asyncio.Queue = asyncio.Queue()
        speech_done = object()
        tts_errors = []
        sentence_buffer = ""
        saw_token = False

        async def tts_worker():
            while True:
                item = await speech_queue.get()

                if item is speech_done:
                    break

                try:
                    await asyncio.to_thread(speak_text_kokoro, item)
                except Exception as exc:
                    tts_errors.append(str(exc))
                    print(f"❌ [Oak Streaming TTS Error]: {exc}")

        tts_task = asyncio.create_task(tts_worker())

        try:
            async for event in self.agent.stream(clean_content, is_owner):
                event_type = event.get("type")

                if event_type == "token":
                    saw_token = True
                    token = str(event.get("text") or "")
                    sentence_buffer += token

                    sentences, sentence_buffer = self._split_speech_sentences(
                        sentence_buffer
                    )

                    for sentence in sentences:
                        cleaned = clean_text_for_speech(sentence)
                        if cleaned:
                            await speech_queue.put(cleaned)

                elif event_type == "reply":
                    reply = str(event.get("text") or "")
                    cleaned = clean_text_for_speech(reply)
                    if cleaned:
                        await speech_queue.put(cleaned)

                elif event_type == "done":
                    done_text = str(event.get("text") or "")

                    if saw_token:
                        if sentence_buffer.strip():
                            cleaned = clean_text_for_speech(sentence_buffer)
                            if cleaned:
                                await speech_queue.put(cleaned)
                    elif done_text:
                        cleaned = clean_text_for_speech(done_text)
                        if cleaned:
                            await speech_queue.put(cleaned)

                yield event

            await speech_queue.put(speech_done)
            await tts_task

            if tts_errors:
                yield {
                    "type": "tts_error",
                    "error": tts_errors[0],
                }

        except Exception:
            await speech_queue.put(speech_done)
            try:
                await tts_task
            except Exception:
                pass
            raise


__all__ = ["VoiceAgent", "VoiceService"]
