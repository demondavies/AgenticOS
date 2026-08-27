"""The Oak persistent local text-to-speech capability.

Owns Kokoro model lifecycle, speech cleanup, and local audio playback.
No Discord or FastAPI dependency.
"""

from __future__ import annotations

import os
import re
import tempfile
import threading
from pathlib import Path

import numpy as np

KOKORO_DIR = Path(r"G:\AgenticOS\models\kokoro")
KOKORO_MODEL_PATH = KOKORO_DIR / "kokoro-v1.0.onnx"
KOKORO_VOICES_PATH = KOKORO_DIR / "voices-v1.0.bin"

# Canonical Oak voice: George 70% + Onyx 30%.
OAK_VOICE_BASE = "bm_george"
OAK_VOICE_SECONDARY = "am_onyx"
OAK_VOICE_BASE_WEIGHT = 0.70
OAK_VOICE_SECONDARY_WEIGHT = 0.30
OAK_LANG = "en-gb"
OAK_SPEED = 1.0

_kokoro = None
_kokoro_lock = threading.Lock()


def _spoken_number(value: str) -> str:
    """Convert an integer string to English words without external packages."""
    try:
        n = int(value)
    except ValueError:
        return value

    ones = [
        "zero", "one", "two", "three", "four", "five", "six", "seven",
        "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
        "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"
    ]
    tens = [
        "", "", "twenty", "thirty", "forty", "fifty",
        "sixty", "seventy", "eighty", "ninety"
    ]

    def under_1000(x):
        parts = []
        if x >= 100:
            parts.append(ones[x // 100] + " hundred")
            x %= 100
            if x:
                parts.append("and")
        if x >= 20:
            parts.append(tens[x // 10])
            if x % 10:
                parts.append(ones[x % 10])
        elif x:
            parts.append(ones[x])
        return " ".join(parts)

    if n == 0:
        return "zero"
    if n < 0:
        return "minus " + _spoken_number(str(-n))

    groups = []
    scales = ["", "thousand", "million", "billion", "trillion"]
    scale = 0
    while n:
        group = n % 1000
        if group:
            groups.append((_under := under_1000(group), scales[scale]))
        n //= 1000
        scale += 1

    words = []
    for number, scale_name in reversed(groups):
        words.append(number)
        if scale_name:
            words.append(scale_name)
    return " ".join(words)


def _number_to_words(match):
    return _spoken_number(match.group(0).replace(",", ""))


def clean_text_for_speech(text: str) -> str:
    """Deterministic speech-polish layer between Hermes and The Oak."""

    s = str(text or "")

    # Speaker labels are UI decoration, never spoken dialogue.
    s = re.sub(
        r"(?im)^\s*(?:\*\*|__)?(?:ARNIE|YOU|USER|ASSISTANT)(?:\*\*|__)?\s*:\s*",
        " ",
        s,
    )

    # Explicit stage directions must never reach Kokoro.
    s = re.sub(
        r"(?is)(?:\\?[*_])\s*(?:speaks?|speaking|says?|smiles?|grins?|"
        r"laughs?|chuckles?|sighs?|nods?|pauses?|whispers?|shouts?|"
        r"looks?|shrugs?|winks?)\b.*?(?:\\?[*_])",
        " ",
        s,
    )
    s = re.sub(
        r"(?i)\b(?:speaks?|speaking)\s+in\s+(?:a\s+)?"
        r"(?:robotic|dramatic|whispering|shouting)\s+voice\b",
        " ",
        s,
    )

    # ------------------------------------------------------------
    # 1. Remove things that are NEVER useful as spoken dialogue.
    # ------------------------------------------------------------
    s = re.sub(r"```[\s\S]*?```", " ", s)
    s = re.sub(r"<tool_call>[\s\S]*?</tool_call>", " ", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)

    # Stage directions / roleplay actions.
    action_pattern = (
        r"smile|smiles|smiling|laugh|laughs|laughing|chuckle|chuckles|"
        r"nod|nods|nodding|sigh|sighs|sighing|pause|pauses|pausing|"
        r"whisper|whispers|whispering|shout|shouts|shouting|"
        r"speaks?|speaking|says?|saying|"
        r"looks?|looking|opens?|opening|closes?|closing|"
        r"checks?|checking|thinks?|thinking|"
        r"shrugs?|shrugging|gestures?|gesturing|"
        r"grins?|grinning|winks?|winking|"
        r"frowns?|frowning|stares?|staring"
    )
    for delimiter in ("*", "_"):
        s = re.sub(
            rf"\{delimiter}(?:[^{delimiter}\n]{{0,220}})\{delimiter}",
            lambda m: "" if re.search(
                rf"\b(?:{action_pattern})\b", m.group(0), re.I
            ) else m.group(0),
            s,
            flags=re.I,
        )
    s = re.sub(
        r"\[[^\]\n]{0,220}\]",
        lambda m: "" if re.search(
            rf"\b(?:{action_pattern})\b", m.group(0), re.I
        ) else m.group(0),
        s,
        flags=re.I,
    )
    s = re.sub(
        r"\([^\)\n]{0,220}\)",
        lambda m: "" if re.search(
            rf"\b(?:{action_pattern})\b", m.group(0), re.I
        ) else m.group(0),
        s,
        flags=re.I,
    )

    # ------------------------------------------------------------
    # 2. Remove UI decoration / emojis.
    # ------------------------------------------------------------
    s = re.sub(
        r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2300-\u23FF\u2B00-\u2BFF\uFE0F]+",
        " ",
        s,
    )

    # Markdown presentation.
    s = re.sub(r"^\s{0,3}#{1,6}\s*", "", s, flags=re.M)
    s = re.sub(r"^\s*[-+]\s+", "", s, flags=re.M)
    s = re.sub(r"^\s*\d+[.)]\s+", "", s, flags=re.M)
    s = re.sub(r"[*_~`]+", "", s)
    s = re.sub(r"\|", " ", s)

    # ------------------------------------------------------------
    # 3. URLs / paths / code-ish text.
    # ------------------------------------------------------------
    s = re.sub(r"https?://\S+", " ", s)
    s = re.sub(r"www\.\S+", " ", s)

    def path_to_speech(match):
        path = match.group(0).rstrip(".,;:!?")
        drive = path[0].upper()
        rest = path[3:] if len(path) >= 3 and path[1:3] == ":\\" else path[2:]
        parts = [p for p in re.split(r"[\\/]+", rest) if p]
        return f"{drive} drive, " + ", ".join(parts) if parts else f"{drive} drive"

    s = re.sub(
        r"\b[A-Za-z]:\\(?:[^<>\s\"'`|?*]+\\?)*[^<>\s\"'`|?*]*",
        path_to_speech,
        s,
    )
    s = re.sub(r"\\+", " ", s)

    # ------------------------------------------------------------
    # 4. Protect proper names / abbreviations containing periods.
    # ------------------------------------------------------------
    protected = {}

    def protect(value):
        key = f"QZPROT{len(protected)}QZ"
        protected[key] = value
        return key

    # Initialed names: Robert E. Howard, J. R. R. Tolkien, C. S. Lewis.
    s = re.sub(
        r"\b(?:[A-Z]\.\s*){1,4}[A-Z][a-zA-Z]+",
        lambda m: protect(m.group(0)),
        s,
    )

    # Titles and common abbreviations.
    s = re.sub(
        r"\b(?:Mr|Mrs|Ms|Dr|Prof|Rev|Gen|St|Mt|Sr|Jr)\.",
        lambda m: protect(m.group(0)),
        s,
        flags=re.I,
    )
    s = re.sub(
        r"\b(?:e\.g|i\.e|etc)\.",
        lambda m: protect(m.group(0)),
        s,
        flags=re.I,
    )
    s = re.sub(
        r"\b(?:U\.S\.A|U\.S|U\.K|U\.N)\.",
        lambda m: protect(m.group(0)),
        s,
        flags=re.I,
    )

    # ------------------------------------------------------------
    # 5. Contextual acronym handling.
    # ------------------------------------------------------------
    # IT is only I.T. when it is clearly the technology noun/adjective.
    s = re.sub(
        r"\bIT(?=\s+(?:department|support|team|system|infrastructure|"
        r"security|administrator|admin|helpdesk|network|operations|"
        r"service|services|project|architecture|policy|staff|manager|"
        r"professional|industry|environment|equipment|budget|desk)\b)",
        "I.T.",
        s,
        flags=re.I,
    )

    # Explicit technical acronyms.
    acronym_map = {
        r"\bGPU\b": "G.P.U.",
        r"\bCPU\b": "C.P.U.",
        r"\bVRAM\b": "V.R.A.M.",
        r"\bRAM\b": "R.A.M.",
        r"\bAPI\b": "A.P.I.",
        r"\bUSB\b": "U.S.B.",
        r"\bLLM\b": "L.L.M.",
        r"\bTTS\b": "T.T.S.",
        r"\bSTT\b": "S.T.T.",
        r"\bAI\b": "A.I.",
        r"\bUI\b": "U.I.",
    }
    for pattern, replacement in acronym_map.items():
        s = re.sub(pattern, replacement, s, flags=re.I)

    # ------------------------------------------------------------
    # 6. Symbols and units.
    # ------------------------------------------------------------
    s = s.replace("&", " and ")
    s = s.replace("@", " at ")
    s = s.replace("→", " then ")
    s = s.replace("—", ", ")
    s = s.replace("–", ", ")
    s = s.replace("°C", " degrees Celsius ")
    s = s.replace("°F", " degrees Fahrenheit ")
    s = s.replace("%", " percent ")

    # ------------------------------------------------------------
    # 7. Numbers: convert useful standalone numbers to English.
    # ------------------------------------------------------------
    # Preserve decimals before integer conversion.
    decimal_tokens = {}
    def protect_decimal(match):
        key = f"QZDEC{len(decimal_tokens)}QZ"
        decimal_tokens[key] = match.group(0)
        return key

    s = re.sub(r"(?<!\w)\d[\d,]*\.\d+(?!\w)", protect_decimal, s)

    # Convert standalone integer numbers up to trillions.
    s = re.sub(r"(?<![\w.])\d[\d,]*(?![\w.])", _number_to_words, s)

    # Restore decimals and turn them into speech-friendly "point".
    for key, value in decimal_tokens.items():
        raw = value.replace(",", "")
        left, right = raw.split(".", 1)
        s = s.replace(key, f"{_spoken_number(left)} point {right}")

    # ------------------------------------------------------------
    # 8. Restore protected names/abbreviations.
    # ------------------------------------------------------------
    for key, value in protected.items():
        s = s.replace(key, value)

    # ------------------------------------------------------------
    # 9. Clean conversational filler only when it is clearly filler.
    # ------------------------------------------------------------
    s = re.sub(r"^\s*(?:um+|uh+|erm+|er+)[,.\s]+", "", s, flags=re.I)
    s = re.sub(r"\b(?:okay|ok),?\s+so,\s+", "", s, flags=re.I)
    s = re.sub(r"\bso basically,\s+", "", s, flags=re.I)

    # ------------------------------------------------------------
    # 10. Final punctuation/whitespace cleanup.
    # ------------------------------------------------------------
    s = re.sub(r"[{}<>\^~]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s+([,.!?;:])", r"\1", s)
    s = re.sub(r"([,.!?;:]){2,}", r"\1", s)

    return s


def split_for_speech(text: str, max_chars: int = 420) -> list[str]:
    """Split spoken text at natural boundaries without breaking names."""
    clean = clean_text_for_speech(text)
    if not clean:
        return []

    # Sentence punctuation is now mostly safe because names and titles
    # have been protected/normalised by clean_text_for_speech.
    pieces = re.split(r"(?<=[.!?])\s+", clean)
    result = []

    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue

        if len(piece) <= max_chars:
            result.append(piece)
            continue

        # Long sentence: prefer clause boundaries before hard whitespace.
        chunks = re.split(r"(?<=[,;:])\s+", piece)
        current = ""

        for chunk in chunks:
            if current and len(current) + 1 + len(chunk) > max_chars:
                result.append(current.strip())
                current = chunk
            else:
                current = f"{current} {chunk}".strip()

        if current:
            result.append(current.strip())

    return result


def _get_kokoro():
    """Load Kokoro once and keep it resident in process memory."""
    global _kokoro

    if _kokoro is not None:
        return _kokoro

    with _kokoro_lock:
        if _kokoro is None:
            if not KOKORO_MODEL_PATH.exists():
                raise FileNotFoundError(f"Missing Kokoro model: {KOKORO_MODEL_PATH}")
            if not KOKORO_VOICES_PATH.exists():
                raise FileNotFoundError(f"Missing Kokoro voices: {KOKORO_VOICES_PATH}")

            try:
                from kokoro_onnx import Kokoro
            except ImportError as exc:
                raise RuntimeError(
                    "The kokoro-onnx Python library is required for persistent TTS. "
                    "Install it with: python -m pip install kokoro-onnx"
                ) from exc

            print("🔊 [Oak] Loading Kokoro engine once...")
            _kokoro = Kokoro(str(KOKORO_MODEL_PATH), str(KOKORO_VOICES_PATH))
            print("✅ [Oak] Kokoro engine loaded and ready.")

    return _kokoro


def speak_text_kokoro(text: str) -> None:
    """Generate and play Oak speech without launching a new Kokoro process."""
    clean_text = clean_text_for_speech(text)

    if not clean_text:
        print("🔊 [Oak] Nothing useful to speak.")
        return

    kokoro = _get_kokoro()

    import soundfile as sf
    import winsound

    print(f"🔊 [Oak Speech] Cleaned: {clean_text[:220]}")
    with _kokoro_lock:
        # kokoro-onnx's Python API expects a voice embedding for blends.
        # Build the canonical Oak embedding from George 70% + Onyx 30%.
        george = kokoro.get_voice_style(OAK_VOICE_BASE)
        onyx = kokoro.get_voice_style(OAK_VOICE_SECONDARY)
        oak_voice = np.add(
            george * OAK_VOICE_BASE_WEIGHT,
            onyx * OAK_VOICE_SECONDARY_WEIGHT,
        )

        samples, sample_rate = kokoro.create(
            clean_text,
            voice=oak_voice,
            speed=OAK_SPEED,
            lang=OAK_LANG,
        )

        with tempfile.NamedTemporaryFile(
            suffix=".wav",
            prefix="arnie_oak_",
            delete=False
        ) as tmp:
            temp_wav = tmp.name

        try:
            sf.write(temp_wav, samples, sample_rate)
            winsound.PlaySound(temp_wav, winsound.SND_FILENAME)
        finally:
            try:
                os.remove(temp_wav)
            except OSError:
                pass

    print("🔊 [Oak] Finished speaking.")


