"""AgenticOS Harness-facing voice adapter.

The implementation remains in service.py; this module provides the stable
orchestration seam for recording and transcription.
"""

from __future__ import annotations

from .service import VoiceEngine, get_voice_engine


class VoiceService:
    def __init__(self, engine: VoiceEngine | None = None) -> None:
        self.engine = engine or get_voice_engine()

    def record(self) -> bytes:
        return self.engine.record_audio_until_silence()

    def transcribe(self, audio_bytes: bytes) -> str:
        return self.engine.transcribe_audio_bytes(audio_bytes)


__all__ = ["VoiceService"]
