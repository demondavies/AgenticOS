"""AgenticOS local voice capability.

Owns microphone capture, VAD, and Faster-Whisper transcription.
No Discord or FastAPI dependency.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel


@dataclass(frozen=True)
class VoiceConfig:
    sample_rate: int = 16000
    channels: int = 1
    chunk_ms: int = 30

    calibration_sec: float = 0.65
    silence_sec: float = 1.05
    start_timeout_sec: float = 8.0
    max_duration_sec: float = 20.0

    pre_roll_sec: float = 0.25
    min_speech_sec: float = 0.25

    speech_multiplier: float = 2.2
    minimum_threshold: float = 180.0

    whisper_model: str = "base.en"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_beam_size: int = 1

    @property
    def chunk_samples(self) -> int:
        return int(self.sample_rate * self.chunk_ms / 1000)


class VoiceEngine:
    """Local microphone + VAD + Faster-Whisper engine."""

    def __init__(self, config: VoiceConfig | None = None) -> None:
        self.config = config or VoiceConfig()

        print("🎙️ [Voice Engine] Initializing local Faster-Whisper model...")

        self.stt_model = WhisperModel(
            self.config.whisper_model,
            device=self.config.whisper_device,
            compute_type=self.config.whisper_compute_type,
        )

        print(
            f"🎙️ [Voice Engine] Ready: "
            f"{self.config.whisper_model} "
            f"({self.config.whisper_device}/{self.config.whisper_compute_type})"
        )

    @staticmethod
    def _audio_level(samples: np.ndarray) -> float:
        """Return RMS level for an int16 mono audio chunk."""

        if samples.size == 0:
            return 0.0

        audio = samples.astype(np.float32)

        return float(
            np.sqrt(
                np.mean(audio * audio)
            )
        )

    def record_audio_until_silence(self) -> bytes:
        """Record microphone audio until sustained silence."""

        cfg = self.config

        print(
            "🎙️ [Voice Engine] "
            "Calibrating microphone / listening for speech..."
        )

        calibration_chunks = max(
            1,
            int(
                cfg.calibration_sec
                * 1000
                / cfg.chunk_ms
            ),
        )

        silence_chunks_required = max(
            1,
            int(
                cfg.silence_sec
                * 1000
                / cfg.chunk_ms
            ),
        )

        start_timeout_chunks = max(
            1,
            int(
                cfg.start_timeout_sec
                * 1000
                / cfg.chunk_ms
            ),
        )

        max_duration_chunks = max(
            1,
            int(
                cfg.max_duration_sec
                * 1000
                / cfg.chunk_ms
            ),
        )

        pre_roll_chunks = max(
            1,
            int(
                cfg.pre_roll_sec
                * 1000
                / cfg.chunk_ms
            ),
        )

        min_speech_chunks = max(
            1,
            int(
                cfg.min_speech_sec
                * 1000
                / cfg.chunk_ms
            ),
        )

        incoming_chunks: list[np.ndarray] = []

        calibration_levels: list[float] = []

        processed_index = 0

        pre_roll: deque[np.ndarray] = deque(
            maxlen=pre_roll_chunks
        )

        recorded_chunks: list[np.ndarray] = []

        speech_started = False

        silence_count = 0
        speech_count = 0

        def callback(
            indata,
            frames,
            time_info,
            status,
        ):
            if status:
                print(
                    f"⚠️ [Voice Engine] "
                    f"Audio status: {status}"
                )

            incoming_chunks.append(
                indata.copy()
            )

        with sd.InputStream(
            samplerate=cfg.sample_rate,
            channels=cfg.channels,
            dtype="int16",
            blocksize=cfg.chunk_samples,
            callback=callback,
        ):

            # ---------------------------------------------------------
            # 1. Calibrate microphone / room noise.
            # ---------------------------------------------------------

            while len(incoming_chunks) < calibration_chunks:
                time.sleep(
                    cfg.chunk_ms / 1000.0
                )

            for chunk in incoming_chunks[:calibration_chunks]:
                calibration_levels.append(
                    self._audio_level(
                        chunk[:, 0]
                    )
                )

            processed_index = calibration_chunks

            noise_floor = (
                float(
                    np.median(
                        calibration_levels
                    )
                )
                if calibration_levels
                else 0.0
            )

            threshold = max(
                noise_floor
                * cfg.speech_multiplier,
                cfg.minimum_threshold,
            )

            print(
                f"🎙️ [Voice Engine] "
                f"Noise floor: {noise_floor:.1f} | "
                f"Speech threshold: {threshold:.1f}"
            )

            # ---------------------------------------------------------
            # 2. Wait for speech.
            # ---------------------------------------------------------

            waited = 0

            while (
                not speech_started
                and waited < start_timeout_chunks
            ):

                time.sleep(
                    cfg.chunk_ms / 1000.0
                )

                while (
                    processed_index
                    < len(incoming_chunks)
                ):

                    chunk = incoming_chunks[
                        processed_index
                    ]

                    processed_index += 1

                    waited += 1

                    pre_roll.append(chunk)

                    level = self._audio_level(
                        chunk[:, 0]
                    )

                    if level >= threshold:
                        speech_count += 1
                    else:
                        speech_count = 0

                    if (
                        speech_count
                        >= min_speech_chunks
                    ):

                        speech_started = True

                        recorded_chunks.extend(
                            list(pre_roll)
                        )

                        print(
                            "🎙️ [Voice Engine] "
                            "Speech detected."
                        )

                        break

                    if waited >= start_timeout_chunks:
                        break

            if not speech_started:

                print(
                    "🎙️ [Voice Engine] "
                    "No speech detected before timeout."
                )

                return b""

            # ---------------------------------------------------------
            # 3. Record until sustained silence.
            # ---------------------------------------------------------

            recorded_duration_chunks = len(
                recorded_chunks
            )

            while (
                recorded_duration_chunks
                < max_duration_chunks
            ):

                time.sleep(
                    cfg.chunk_ms / 1000.0
                )

                while (
                    processed_index
                    < len(incoming_chunks)
                ):

                    chunk = incoming_chunks[
                        processed_index
                    ]

                    processed_index += 1

                    recorded_chunks.append(
                        chunk
                    )

                    recorded_duration_chunks += 1

                    level = self._audio_level(
                        chunk[:, 0]
                    )

                    if level >= threshold:

                        speech_count += 1
                        silence_count = 0

                    else:

                        silence_count += 1

                    if (
                        silence_count
                        >= silence_chunks_required
                        and speech_count
                        >= min_speech_chunks
                    ):

                        print(
                            "🎙️ [Voice Engine] "
                            "Silence detected. "
                            "Recording complete."
                        )

                        break

                if (
                    silence_count
                    >= silence_chunks_required
                    and speech_count
                    >= min_speech_chunks
                ):
                    break

            if (
                recorded_duration_chunks
                >= max_duration_chunks
            ):
                print(
                    "🎙️ [Voice Engine] "
                    "Maximum recording duration reached."
                )

        if not recorded_chunks:
            return b""

        # -------------------------------------------------------------
        # 4. Flatten audio into raw int16 PCM.
        #
        # The transcription layer below intentionally consumes this
        # exact format and converts it to float32.
        # -------------------------------------------------------------

        audio = np.concatenate(
            [
                chunk[:, 0]
                for chunk in recorded_chunks
            ]
        ).astype(np.int16)

        duration = (
            len(audio)
            / cfg.sample_rate
        )

        print(
            f"🎙️ [Voice Engine] "
            f"Captured {duration:.2f}s of audio."
        )

        return audio.tobytes()

    def transcribe_audio_bytes(
        self,
        audio_bytes: bytes,
    ) -> str:
        """Transcribe raw 16-bit mono PCM at 16 kHz."""

        if not audio_bytes:
            return ""

        # Convert the recorder's raw int16 PCM into the normalized
        # float32 waveform expected by Faster-Whisper.
        audio = np.frombuffer(
            audio_bytes,
            dtype=np.int16,
        ).astype(np.float32)

        audio /= 32768.0

        segments, _ = self.stt_model.transcribe(
            audio,
            beam_size=self.config.whisper_beam_size,
        )

        transcript = " ".join(
            segment.text
            for segment in segments
        ).strip()

        print(
            f"🗣️ [Voice Transcribed]: "
            f"'{transcript}'"
        )

        return transcript


_engine: VoiceEngine | None = None


def get_voice_engine() -> VoiceEngine:
    """Return the process-wide VoiceEngine singleton."""

    global _engine

    if _engine is None:
        _engine = VoiceEngine()

    return _engine


def record_audio_until_silence() -> bytes:
    """Record local speech through the shared VoiceEngine."""

    return (
        get_voice_engine()
        .record_audio_until_silence()
    )


def transcribe_audio_bytes(
    audio_bytes: bytes,
) -> str:
    """Transcribe captured audio through the shared VoiceEngine."""

    return (
        get_voice_engine()
        .transcribe_audio_bytes(
            audio_bytes
        )
    )