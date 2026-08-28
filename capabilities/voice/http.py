"""HTTP adapter for the AgenticOS voice capability.

Owns FastAPI-facing serialization and response handling for voice.
Voice orchestration remains inside VoiceService/VoiceAgent; this module
contains no Discord logic and does not implement model, intent, or TTS policy.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi.responses import JSONResponse, StreamingResponse


class VoiceHTTPAdapter:
    """Translate HTTP requests into canonical VoiceService operations."""

    def __init__(self, voice_service) -> None:
        self.voice_service = voice_service

    async def transcribe(self):
        try:
            audio_bytes = await asyncio.to_thread(self.voice_service.record)
            text = await asyncio.to_thread(
                self.voice_service.transcribe,
                audio_bytes,
            )
            return JSONResponse(content={"transcription": text})
        except Exception as exc:
            print(f"❌ [Voice Transcription Error]: {exc}")
            return JSONResponse(
                status_code=500,
                content={"error": str(exc)},
            )

    async def listen(self):
        try:
            audio_bytes = await asyncio.to_thread(self.voice_service.record)
            text = await asyncio.to_thread(
                self.voice_service.transcribe,
                audio_bytes,
            )

            if not text:
                return JSONResponse(
                    content={
                        "reply": "I couldn't hear anything! Speak louder, soldier!",
                        "transcription": "",
                    }
                )

            reply = ""
            async for event in self.voice_service.stream(text, is_owner=True):
                if event.get("type") in {"done", "reply"}:
                    reply = str(event.get("text") or reply)

            return JSONResponse(
                content={
                    "reply": reply,
                    "transcription": text,
                }
            )
        except Exception as exc:
            print(f"❌ [Voice API Error]: {exc}")
            return JSONResponse(
                status_code=500,
                content={"error": str(exc)},
            )

    def stream_response(self, text: str, *, is_owner: bool = True):
        async def event_generator():
            full_reply = ""

            try:
                async for event in self.voice_service.stream(
                    text,
                    is_owner=is_owner,
                ):
                    event_type = event.get("type")
                    event_text = str(event.get("text") or "")

                    if event_type == "token" and event_text:
                        full_reply += event_text
                    elif event_type == "reply" and event_text:
                        full_reply = event_text
                    elif event_type == "done" and event_text:
                        full_reply = event_text

                    output_event = dict(event)
                    if event_type == "done":
                        output_event["reply"] = full_reply

                    yield (
                        "data: "
                        + json.dumps(output_event, ensure_ascii=False)
                        + "\n\n"
                    )

            except Exception as exc:
                print(f"❌ [Voice Streaming Error]: {exc}")
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "type": "error",
                            "error": str(exc),
                        },
                        ensure_ascii=False,
                    )
                    + "\n\n"
                )

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    async def speak(self, text: str):
        try:
            await asyncio.to_thread(self.voice_service.speak, text)
            return JSONResponse(content={"status": "success"})
        except Exception as exc:
            print(f"❌ [TTS Error]: {exc}")
            return JSONResponse(
                status_code=500,
                content={"error": str(exc)},
            )


__all__ = ["VoiceHTTPAdapter"]
