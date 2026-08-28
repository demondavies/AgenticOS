"""Discord voice capability.

Joins a Discord voice channel, speaks text using the Kokoro TTS engine,
then disconnects. Requires PyNaCl and FFmpeg on PATH.
No FastAPI or bot.py dependency — only discord.py and oak.
"""

from __future__ import annotations

import os
import tempfile

import soundfile as sf


class DiscordVoiceSpeaker:
    """Speak text into a Discord voice channel using the Oak TTS engine."""

    async def speak(self, voice_channel, text: str) -> None:
        """Join voice_channel, speak text, then disconnect.

        Safe to call from an asyncio context — the blocking Kokoro
        generation runs in a thread executor so it does not block the
        event loop.
        """
        import asyncio
        import discord
        from capabilities.voice.oak import generate_audio_samples

        loop = asyncio.get_event_loop()
        samples, sample_rate = await loop.run_in_executor(
            None, generate_audio_samples, text
        )

        if samples is None:
            return

        # Write the audio to a temp WAV on disk.
        with tempfile.NamedTemporaryFile(
            suffix=".wav",
            prefix="arnie_discord_",
            delete=False,
        ) as tmp:
            temp_wav = tmp.name

        try:
            sf.write(temp_wav, samples, sample_rate)

            voice_client: discord.VoiceClient = await voice_channel.connect()
            try:
                source = discord.FFmpegPCMAudio(temp_wav)
                # Wait for playback to finish before disconnecting.
                finished = asyncio.Event()

                def after_play(err):
                    if err:
                        print(f"❌ [Discord Voice] Playback error: {err}")
                    loop.call_soon_threadsafe(finished.set)

                voice_client.play(source, after=after_play)
                await finished.wait()
            finally:
                await voice_client.disconnect()
        finally:
            try:
                os.remove(temp_wav)
            except OSError:
                pass
