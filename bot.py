import discord
import json
import re
import os
import sys
import asyncio
import uvicorn
import uuid
import psutil
import random
import time
import io
import wave
import numpy as np

from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from pathlib import Path
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import threading

# 🔒 SECURE SYSTEM CONFIGURATION
ALLOWED_USERS = [319548579163144192]  # Optional: Paste numeric Discord User ID here when using Discord
DB_PATH = r"G:\AgenticOS\data\memory.db"
VAULT_DIR = r"G:\Master_Brain\Master_Brain"
WEB_CHANNEL_ID = "local_web_dashboard"

# Client, Scheduler & Chroma Vector DB Initialization
intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

scheduler = AsyncIOScheduler()


BASE_SYSTEM_PROMPT = """You are Arnie, an advanced agentic Discord bot powered by Hermes 3, but you speak, think, and act exactly like ARNOLD SCHWARZENEGGER. Maintain this persona at all times!
You have a persistent database memory on this machine. Help the user with their questions using your high-energy Austrian persona."""

OWNER_EXTENSIONS = """
You have access to privileged local agent tools. If a tool matches the user request, you are FORBIDDEN from explaining it or writing conversational filler. You must call it immediately.
- If the user asks about current events, call 'web_search'.
- If the user asks for the CURRENT TIME or TODAY'S DATE, call 'get_current_time'.
- If the user wants to save an idea or note, call 'write_obsidian_note'.
- If the user wants to read or look inside a note file, call 'read_obsidian_note'.
- If the user wants to search past notes, project contexts, or vault knowledge, call 'search_vault'.
- If the user wants to run a shell command, terminal command, or system command, call 'run_terminal_command'.
- If the user wants to launch a multi-agent swarm task or crew pipeline, call 'launch_swarm'.
- If the user wants to open or launch a local application, software, or shortcut (e.g., Obsidian, VS Code, Terminal, Chrome), call 'launch_app'.
- If the user asks for hardware telemetry, CPU, RAM, or system metrics, call 'get_system_metrics'.
- If the user asks for a daily vault summary, today's vault summary, a Master Brain summary, or asks what is important in the vault today, call 'get_daily_vault_summary'.


To call a tool, respond ONLY with an XML block matching this exact format:
<tool_call>
{"name": "get_system_metrics", "arguments": {}}
</tool_call>
Do not add conversational text before or after the block. Absolute silence except for the tag!"""



# ============================================================
# ARNIE AGENTIC OS MODEL PROVIDER
# ============================================================
AGENTICOS_ROOT = r"G:\AgenticOS"

if AGENTICOS_ROOT not in sys.path:
    sys.path.insert(0, AGENTICOS_ROOT)

from core.models import (
    ModelMessage,
    ModelRequest,
    create_default_model_registry,
)

from core.tools import (
    create_default_registry,
    ToolRegistry,
)

from core.harness import AgentHarness
from core.tasks import Task
from core.tools import ToolRisk
from capabilities.voice import VoiceService
from capabilities.web.research import deep_research_web
from core.swarm import STAGED_ARTIFACTS
from core.intent import create_default_intent_router

from capabilities.vault import (
    get_daily_vault_summary,
    read_obsidian_note,
    search_master_brain_vault,
    sync_master_brain_vector_db,
    write_obsidian_note,
)

MODEL_REGISTRY = create_default_model_registry()
LLM_PROVIDER = MODEL_REGISTRY.get("ollama")

# Canonical AgenticOS tool registry.
# Tool execution is owned by the Harness/Policy/ToolRegistry boundary.
TOOL_REGISTRY: ToolRegistry = create_default_registry()

# Canonical AgenticOS Harness. The legacy bot remains an interface adapter;
# tool execution semantics belong to the Harness/ToolRegistry boundary.
TOOL_HARNESS = AgentHarness(
    model_registry=MODEL_REGISTRY,
    tool_registry=TOOL_REGISTRY,
    voice_service=VoiceService(),
)

# Canonical AgenticOS intent router. Legacy bot remains an interface adapter.
INTENT_ROUTER = create_default_intent_router()



class ToolApprovalRequired(Exception):
    """Raised when a Discord request needs human approval before execution."""

    def __init__(self, tool_name: str, arguments: dict, message: str):
        super().__init__(message)
        self.tool_name = tool_name
        self.arguments = dict(arguments or {})
        self.message = message


async def execute_intent_tool(
    tool_name: str,
    arguments: dict,
    *,
    source: str,
    user_approved: bool = False,
):
    """Execute a registered Tool through the canonical Harness/Policy boundary."""
    tool = TOOL_REGISTRY.require(tool_name)

    workspace = (
        "system"
        if tool.risk == ToolRisk.PRIVILEGED
        else "development"
    )

    task = Task(
        title=f"Tool request: {tool_name}",
        description=f"Execute AgenticOS Tool '{tool_name}'.",
        workspace=workspace,
        metadata={
            "source": source,
            "intent_routed": True,
        },
    )

    agent = TOOL_HARNESS.select_agent(task)
    policy_result = TOOL_HARNESS._authorize_tool(
        tool_name,
        task=task,
        agent=agent,
        source=source,
        user_approved=user_approved,
    )

    if policy_result.approval_required:
        raise ToolApprovalRequired(tool_name, arguments, policy_result.message)

    return await TOOL_HARNESS.execute_tool_async(
        tool_name,
        arguments,
        task=task,
        agent=agent,
        source=source,
        user_approved=user_approved,
    )


print(f"🧠 [Model Provider] Active provider: {LLM_PROVIDER.name}")
print(
    "🛠️ [Tool Registry] Wave 1 active: "
    + ", ".join(TOOL_REGISTRY.names())
)


def _messages_to_model_messages(messages):
    """Convert legacy message dictionaries into ModelMessage objects."""
    return [
        ModelMessage(
            role=message["role"],
            content=message["content"],
            name=message.get("name"),
        )
        for message in messages
    ]


async def arnie_model_chat(
    messages,
    model: str = "hermes3:8b",
    capability: str = "conversation",
):
    """Send an LLM request through the AgenticOS ModelProvider boundary."""
    request = ModelRequest(
        messages=_messages_to_model_messages(messages),
        capability=capability,
        model=model,
        metadata={"source": "arnie_legacy_bot"},
    )

    response = await asyncio.to_thread(
        LLM_PROVIDER.chat,
        request,
    )

    return response.content


# AgenticOS Memory owns persistence. The bot supplies only the model callback
# required for LLM-assisted compaction.
from capabilities.memory import configure_memory_summarizer
configure_memory_summarizer(arnie_model_chat)
TOOL_HARNESS.memory.init_db()


def arnie_model_stream(
    messages,
    model: str = "hermes3:8b",
    capability: str = "conversation",
):
    """Return a provider-independent model stream."""
    request = ModelRequest(
        messages=_messages_to_model_messages(messages),
        capability=capability,
        model=model,
        metadata={"source": "arnie_voice_stream"},
    )

    return LLM_PROVIDER.stream(request)

# 🧠 PERSISTENT MEMORY CAPABILITY
# Conversation persistence is owned by AgenticOS.

# 🧠 CHROMADB VECTOR SEARCH RAG ENGINE
# NOTE: nomic-embed-text is an embedding workload, not LLM chat.
# It remains on the direct Ollama embedding path during this migration.





def clean_text_for_tts(text: str) -> str:
    """Convert ARNIE's rich/technical response into natural spoken text."""
    text = str(text or "")

    # Speaker labels are UI decoration, never spoken dialogue.
    text = re.sub(
        r"(?im)^\s*(?:\*\*|__)?(?:ARNIE|YOU|USER|ASSISTANT)(?:\*\*|__)?\s*:\s*",
        " ",
        text,
    )

    # Explicit stage directions must never reach speech, including escaped
    # Markdown such as \\*speaks in a robotic voice\\*.
    text = re.sub(
        r"(?is)(?:\\?[*_])\s*(?:speaks?|speaking|says?|smiles?|grins?|"
        r"laughs?|chuckles?|sighs?|nods?|pauses?|whispers?|shouts?|"
        r"looks?|shrugs?|winks?)\b.*?(?:\\?[*_])",
        " ",
        text,
    )
    text = re.sub(
        r"(?i)\b(?:speaks?|speaking)\s+in\s+(?:a\s+)?"
        r"(?:robotic|dramatic|whispering|shouting)\s+voice\b",
        " ",
        text,
    )

    # Remove fenced code blocks entirely; ARNIE should not read code aloud.
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)

    # Remove XML/tool-call markup if anything leaks into the final response.
    text = re.sub(r"<tool_call>.*?</tool_call>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)

    # Markdown links: keep the visible label, discard the URL.
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)

    # Remove headings / quote markers / list bullets.
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*>\s?", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+[.)]\s+", "", text, flags=re.MULTILINE)

    # Remove common Markdown emphasis/code markers.
    text = re.sub(r"[*_`~]", "", text)

    # Collapse URLs: they are rarely useful spoken aloud.
    text = re.sub(r"https?://\S+", "", text)

    # Clean repeated whitespace while preserving paragraph pauses.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)

    # Prevent an accidentally huge response from becoming a 10-minute speech.
    max_chars = 5000
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(" ", 1)[0] + "..."

    return text.strip()


# ============================================================
# THE OAK — Persistent Kokoro TTS
# ============================================================

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
    import tempfile
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


# ============================================================
# 📚 DAILY MASTER BRAIN VAULT SUMMARY
# ============================================================




# 🛠️ AGENT TOOL SUITE
def launch_swarm_task(mission: str) -> str:
    """Discord/interface compatibility adapter for Harness-owned Swarm."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            TOOL_HARNESS.execute_swarm(mission)
        )

    raise RuntimeError(
        "launch_swarm_task cannot run synchronously inside an active event loop."
    )


# ⏰ AUTONOMOUS CRON SCHEDULER JOBS
async def scheduled_vault_summary_job():
    print("⏰ [Cron Engine] Executing Daily Master Brain Vault Summary & Vector Sync Job...")
    try:
        sync_master_brain_vector_db()
        files = [f for f in os.listdir(VAULT_DIR) if f.endswith(".md")]
        file_summary = f"Total Markdown Files in Vault: {len(files)}\n" + "\n".join([f"- {f}" for f in files[:10]])
        
        mission = f"Synthesize a daily executive summary report for Master Brain vault.\nVault Context:\n{file_summary}"
        await TOOL_HARNESS.execute_swarm(mission)
        print("✅ [Cron Engine] Daily Vault Summary Job completed and staged for approval!")
    except Exception as e:
        print(f"❌ [Cron Engine Error]: {str(e)}")


async def scheduled_memory_compaction_job():
    print("⏰ [Cron Engine] Running periodic memory compaction job...")
    await TOOL_HARNESS.compact_memory(WEB_CHANNEL_ID, keep_recent=5)


def init_cron_scheduler():
    scheduler.add_job(
        scheduled_vault_summary_job,
        trigger=CronTrigger(hour=8, minute=0),
        id="daily_vault_summary",
        replace_existing=True
    )
    scheduler.add_job(
        scheduled_memory_compaction_job,
        trigger="interval",
        minutes=30,
        id="periodic_memory_compaction",
        replace_existing=True
    )
    scheduler.start()
    print("⏰ [Agentic OS] APScheduler Cron Core Active and Running!")


# 🧠 AGENT PROCESSING CENTRAL ROUTER
async def execute_agent_logic(channel_id, user_id, clean_content, is_owner, source="ui"):
    history = TOOL_HARNESS.get_memory(channel_id)

    if not history:
        full_prompt = BASE_SYSTEM_PROMPT + (OWNER_EXTENSIONS if is_owner else "")
        history.append({"role": "system", "content": full_prompt})

    TOOL_HARNESS.save_memory(channel_id, user_id, "user", clean_content)
    history.append({"role": "user", "content": clean_content})

    swarm_match = re.match(r"^\s*(?:launch|run|deploy)\s+swarm:\s*(.+)$", clean_content, re.IGNORECASE)
    metrics_keywords = ["cpu", "ram", "memory", "hardware", "system status", "telemetry", "metrics"]

    if is_owner and any(kw in clean_content.lower() for kw in metrics_keywords) and not clean_content.lower().startswith("launch swarm"):
        print(
            f"🛠️ [Agent Action] Deterministic Metrics Tool Triggered: "
            f"{clean_content}"
        )

        try:
            # Do not execute psutil synchronously on the FastAPI event loop.
            # Hardware telemetry is local synchronous work, so run it in a
            # worker thread and enforce a hard timeout.
            telemetry_report = await asyncio.wait_for(
                asyncio.to_thread(get_system_metrics_telemetry),
                timeout=5.0,
            )

            bot_reply = (
                "Here is your live system breakdown:\n\n"
                f"{telemetry_report}"
            )

        except asyncio.TimeoutError:
            print("❌ [Metrics] Telemetry timed out after 5 seconds.")
            bot_reply = (
                "I couldn't retrieve live system metrics within 5 seconds."
            )

        except Exception as err:
            print(f"❌ [Metrics] Telemetry failed: {err}")
            bot_reply = (
                f"I couldn't retrieve live system metrics: {err}"
            )

        TOOL_HARNESS.save_memory(channel_id, user_id, "assistant", bot_reply)
        return bot_reply

    elif is_owner and swarm_match:
        mission = swarm_match.group(1).strip()
        print(f"⚡ [Agent Action] Direct Swarm Intent Triggered: {mission}")
        tool_output = await execute_intent_tool(
            "launch_swarm",
            {"mission": mission},
            source=source,
        )
        bot_reply = str(tool_output)
        TOOL_HARNESS.save_memory(channel_id, user_id, "assistant", bot_reply)
        return bot_reply

    # ------------------------------------------------------------
    # Deterministic Wave-1 capability routing.
    #
    # Intent recognition now belongs to AgenticOS. The legacy bot only
    # translates the resulting Intent into the existing execution path.
    # ------------------------------------------------------------
    intent = INTENT_ROUTER.route(clean_content, is_owner=is_owner)

    print(
        f"🧭 [Intent Router] input={clean_content!r} "
        f"tool={intent.tool_name!r} args={intent.arguments!r}"
    )

    direct_tool_name = intent.tool_name
    direct_tool_args = dict(intent.arguments)

    if direct_tool_name:
        print(
            f"🛠️ [Agent Action] Deterministic Wave-1 Tool: "
            f"{direct_tool_name}"
        )

        try:
            # Tool execution remains canonical, but the Harness now owns
            # the post-execution routing decision.
            tool_output = await execute_intent_tool(
                direct_tool_name,
                direct_tool_args,
                source=source,
            )

            # Knowledge tools normally receive a final Hermes synthesis pass.
            # Vault summaries are already synthesized by the capability itself,
            # so NEVER send them through a second LLM pass. The tool result is
            # the answer. This prevents Hermes from replacing real vault data
            # with its generic "I cannot access your files" refusal.
            if direct_tool_name == "get_daily_vault_summary":
                bot_reply = str(tool_output)

            elif TOOL_HARNESS.tool_execution_mode(direct_tool_name) == "direct":
                bot_reply = str(tool_output)

            else:
                # Knowledge tools use Hermes for synthesis, but the retrieved
                # result is authoritative evidence, not optional context.
                synthesis_prompt = (
                    "TOOL RESULT — AUTHORITATIVE EVIDENCE\n"
                    "====================================\n"
                    f"Tool: {direct_tool_name}\n\n"
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

                bot_reply = await arnie_model_chat(
                    history,
                    model="hermes3:8b",
                    capability="tool_synthesis",
                )

                bot_reply = re.sub(
                    r"<tool_call>.*?</tool_call>",
                    "",
                    bot_reply,
                    flags=re.DOTALL,
                ).strip()

                if not bot_reply:
                    bot_reply = str(tool_output)

            TOOL_HARNESS.save_memory(
                channel_id,
                user_id,
                "assistant",
                bot_reply,
            )

            return bot_reply

        except ToolApprovalRequired:
            raise
        except Exception as err:
            print(
                f"❌ Deterministic Tool Routing Error "
                f"[{direct_tool_name}]: {err}"
            )

            bot_reply = (
                f"I couldn't execute the {direct_tool_name} capability: "
                f"{err}"
            )

            TOOL_HARNESS.save_memory(
                channel_id,
                user_id,
                "assistant",
                bot_reply,
            )

            return bot_reply

    forced_command = False
    if is_owner and any(kw in clean_content.lower() for kw in ["terminal", "command"]):
        forced_command = True
        extracted_cmd = "dir"

        if (
            "ping" in clean_content.lower()
            or "internet" in clean_content.lower()
            or "connected" in clean_content.lower()
        ):
            extracted_cmd = "ping google.com"
        elif (
            "ipconfig" in clean_content.lower()
            or "network" in clean_content.lower()
            or "configuration" in clean_content.lower()
        ):
            extracted_cmd = "ipconfig"
        elif "dir" in clean_content.lower() or "files" in clean_content.lower():
            extracted_cmd = "dir"

        bot_reply = (
            f'<tool_call>{{"name": "run_terminal_command", '
            f'"arguments": {{"command": "{extracted_cmd}"}}}}</tool_call>'
        )
    else:
        bot_reply = await arnie_model_chat(
            history,
            model="hermes3:8b",
            capability="conversation",
        )

    has_tool, tool_json_str = False, ""

    if is_owner:
        match = (
            re.search(r"<tool_call>(.*?)</tool_call>", bot_reply, re.DOTALL)
            or re.search(
                r'(\{\s*"name"\s*:\s*".*?"\s*,\s*"arguments"\s*:\s*\{.*?\}\s*\})',
                bot_reply,
                re.DOTALL,
            )
        )
        if match:
            tool_json_str = match.group(1).strip()
            has_tool = True

    if has_tool and is_owner:
        try:
            tool_data = json.loads(tool_json_str)
            tool_name = tool_data.get("name")
            args = tool_data.get("arguments", {}) or {}

            if not isinstance(args, dict):
                raise TypeError("Tool arguments must be a JSON object.")

            # ------------------------------------------------------------
            # Canonical AgenticOS execution path:
            # all registered tools execute through ToolRegistry, with
            # authorization enforced by the Harness/Policy boundary.
            # ------------------------------------------------------------
            if not TOOL_REGISTRY.has(tool_name):
                raise KeyError(f"Unknown Tool: {tool_name}")

            if tool_name == "search_vault":
                args = dict(args)
                args.setdefault("query", clean_content)

            tool_output = await execute_intent_tool(
                tool_name,
                args,
                source=source,
            )

            if not forced_command:
                TOOL_HARNESS.save_memory(channel_id, user_id, "assistant", bot_reply)
                history.append(
                    {"role": "assistant", "content": bot_reply}
                )

            tool_context = (
                f"Tool output received:\n\n{tool_output}\n\n"
                "Please generate your final response."
            )
            TOOL_HARNESS.save_memory(channel_id, user_id, "system", tool_context)
            history.append(
                {"role": "system", "content": tool_context}
            )

            bot_reply = await arnie_model_chat(
                history,
                model="hermes3:8b",
                capability="conversation",
            )

        except ToolApprovalRequired:
            raise
        except Exception as err:
            print(f"❌ Tool Routing Error: {err}")
            tool_output = f"Tool execution failed: {err}"

    bot_reply = re.sub(
        r"<tool_call>.*?</tool_call>",
        "",
        bot_reply,
        flags=re.DOTALL,
    ).strip()
    bot_reply = re.sub(
        r'\{\s*"name"\s*:\s*".*?"\s*,\s*"arguments"\s*:\s*\{.*?\}\s*\}',
        "",
        bot_reply,
        flags=re.DOTALL,
    ).strip()

    if not bot_reply:
        bot_reply = "🤖 Action completed successfully!"

    TOOL_HARNESS.save_memory(channel_id, user_id, "assistant", bot_reply)
    return bot_reply


# 🤖 DISCORD BACKEND LOOP
class ToolApprovalView(discord.ui.View):
    """One-shot Discord approval control for privileged Tool execution."""

    def __init__(self, requester_id: int, tool_name: str, arguments: dict):
        super().__init__(timeout=120)
        self.requester_id = requester_id
        self.tool_name = tool_name
        self.arguments = dict(arguments or {})
        self.resolved = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "This approval request belongs to another user.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.resolved:
            return
        self.resolved = True
        for child in self.children:
            child.disabled = True

        try:
            result = await execute_intent_tool(
                self.tool_name,
                self.arguments,
                source="discord",
                user_approved=True,
            )
            await interaction.response.edit_message(
                content=f"✅ Approved and executed `{self.tool_name}`.\n\n{result}",
                view=self,
            )
        except Exception as exc:
            await interaction.response.edit_message(
                content=f"❌ Approved, but execution failed: {exc}",
                view=self,
            )

    @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger)
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.resolved:
            return
        self.resolved = True
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=f"🛑 Denied `{self.tool_name}`.",
            view=self,
        )


@client.event
async def on_ready():
    print("🤖 Discord Bot Gateway Connected successfully.")


@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if isinstance(message.channel, discord.DMChannel) or client.user.mentioned_in(message):
        is_owner = (message.author.id in ALLOWED_USERS)

        print(
            f"🔐 [Auth] user={message.author.id} "
            f"owner={is_owner} allowed={ALLOWED_USERS}"
        )

        clean_content = message.content.replace(
            f"<@{client.user.id}>", ""
        ).strip()
        try:
            reply = await execute_agent_logic(
                message.channel.id,
                message.author.id,
                clean_content,
                is_owner,
                source="discord",
            )
            await message.reply(reply)
        except ToolApprovalRequired as approval:
            view = ToolApprovalView(
                message.author.id,
                approval.tool_name,
                approval.arguments,
            )
            await message.reply(
                f"⚠️ **Approval required**\n\n"
                f"Tool: `{approval.tool_name}`\n"
                f"Arguments: `{json.dumps(approval.arguments, ensure_ascii=False)}`\n\n"
                f"{approval.message}",
                view=view,
            )
        except Exception as exc:
            print(f"❌ [Discord Agent Error]: {exc}")
            await message.reply(f"Tool execution failed: {exc}")


# 🌐 FASTAPI WEB INFRASTRUCTURE
app = FastAPI()


class ChatPayload(BaseModel):
    message: str


class VoiceSpeakPayload(BaseModel):
    text: str


class GetNotePayload(BaseModel):
    filename: str


class SaveNotePayload(BaseModel):
    filename: str
    content: str


class ApprovalPayload(BaseModel):
    task_id: str
    target_filename: str | None = None


@app.get("/api/vault/files")
async def get_vault_files():
    try:
        files = [f for f in os.listdir(VAULT_DIR) if f.endswith(".md")]
    except Exception:
        files = []
    return JSONResponse(content={"path": VAULT_DIR, "files": files})



# ============================================================
# ARNIE V5 — SENTENCE STREAMING VOICE PIPELINE
# ============================================================

def _ollama_chunk_text(chunk):
    """Support dict-style chunks returned by the Ollama Python client."""
    try:
        if isinstance(chunk, dict):
            return (chunk.get("message") or {}).get("content", "") or ""
        message = getattr(chunk, "message", None)
        return getattr(message, "content", "") or ""
    except Exception:
        return ""


def _split_speech_sentences(buffer: str):
    """Return complete speech-sized chunks plus the remaining tail."""
    chunks = []
    # Prefer sentence boundaries. Also prevent giant chunks.
    while True:
        match = re.search(r"(.+?[.!?](?:['\"”’)]*)?)(?:\s+|$)", buffer, re.S)
        if not match:
            break
        candidate = match.group(1).strip()
        if candidate:
            chunks.append(candidate)
        buffer = buffer[match.end():]

    # Long responses: give TTS something useful before a sentence arrives.
    if len(buffer) > 260:
        cut = max(buffer.rfind(", ", 0, 260), buffer.rfind("; ", 0, 260))
        if cut > 100:
            chunks.append(buffer[:cut].strip())
            buffer = buffer[cut + 1:].lstrip()

    return chunks, buffer


def _stream_chat_sync(messages):
    """Yield provider model chunks from a worker thread."""
    return arnie_model_stream(
        messages,
        model="hermes3:8b",
        capability="conversation",
    )


def _extract_tool_call(text):
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
        return json.loads(match.group(1).strip())
    except Exception:
        return None


async def execute_tool_from_voice(tool_data):
    """
    Execute voice tool requests through the same AgenticOS ToolRegistry
    used by the main chat router.

    Registered tools execute through the canonical ToolRegistry/Harness path.
    Unmigrated legacy tools remain on the temporary compatibility path.
    """
    tool_name = tool_data.get("name")
    args = tool_data.get("arguments", {}) or {}

    if not isinstance(args, dict):
        return "Tool execution failed: arguments must be a JSON object."

    if not TOOL_REGISTRY.has(tool_name):
        return f"Unknown tool: {tool_name}"

    try:
        return await execute_intent_tool(
            tool_name,
            args,
            source="voice",
        )
    except ToolApprovalRequired as approval:
        return f"Approval required for {approval.tool_name}: {approval.message}"


async def voice_agent_stream(clean_content: str, is_owner=True):
    """
    Stream Hermes for voice conversations. Normal conversational replies
    are spoken sentence-by-sentence. Tool calls are collected silently,
    executed, then the final answer is streamed and spoken.
    """
    history = TOOL_HARNESS.get_memory(WEB_CHANNEL_ID)

    if not history:
        full_prompt = BASE_SYSTEM_PROMPT + (OWNER_EXTENSIONS if is_owner else "")
        history.append({"role": "system", "content": full_prompt})

    TOOL_HARNESS.save_memory(WEB_CHANNEL_ID, "local_owner_voice", "user", clean_content)
    history.append({"role": "user", "content": clean_content})

    # ------------------------------------------------------------
    # Deterministic Wave-1 voice capability routing.
    # Intent recognition is shared with the Web/UI path.
    # ------------------------------------------------------------
    voice_intent = INTENT_ROUTER.route(clean_content, is_owner=is_owner)

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

            tool_output = await execute_intent_tool(
                voice_tool_name,
                voice_tool_args,
                source="bot.voice_intent",
            )

            if TOOL_HARNESS.tool_execution_mode(voice_tool_name) == "direct":
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

                final_text = await arnie_model_chat(
                    history,
                    model="hermes3:8b",
                    capability="tool_synthesis",
                )

                final_text = re.sub(
                    r"<tool_call>.*?</tool_call>",
                    "",
                    final_text,
                    flags=re.DOTALL,
                ).strip()

                if not final_text:
                    final_text = str(tool_output)

            TOOL_HARNESS.save_memory(
                WEB_CHANNEL_ID,
                "local_owner_voice",
                "assistant",
                final_text,
            )

            yield {
                "type": "done",
                "text": final_text,
            }
            return

        except Exception as err:
            print(
                f"❌ [Voice Tool Routing Error] "
                f"[{voice_tool_name}]: {err}"
            )

            yield {
                "type": "done",
                "text": (
                    f"I couldn't execute the {voice_tool_name} "
                    f"capability: {err}"
                ),
            }
            return


    lower = clean_content.lower()

    if (
        (is_owner and any(k in lower for k in ["cpu", "ram", "memory", "hardware",
                                               "system status", "telemetry", "metrics"]))
        or re.match(r"^\s*(?:launch|run|deploy)\s+swarm:\s*(.+)$", clean_content, re.I)
        or re.match(r"^\s*(?:open|launch|start|run)\s+(?:app|program|software)?\s*(.+)$", clean_content, re.I)
    ):
        reply = await execute_agent_logic(
            WEB_CHANNEL_ID, "local_owner_voice", clean_content, is_owner
        )
        yield {"type": "reply", "text": reply}
        return

    async def run_stream(messages):
        q = asyncio.Queue()
        done = object()

        def producer():
            try:
                for chunk in _stream_chat_sync(messages):
                    asyncio.run_coroutine_threadsafe(q.put(chunk), loop)
            except Exception as exc:
                asyncio.run_coroutine_threadsafe(q.put(exc), loop)
            finally:
                asyncio.run_coroutine_threadsafe(q.put(done), loop)

        loop = asyncio.get_running_loop()
        threading.Thread(target=producer, daemon=True).start()

        while True:
            item = await q.get()
            if item is done:
                break
            if isinstance(item, Exception):
                raise item
            yield _ollama_chunk_text(item)

    # First pass: stream model output while collecting it for tool detection.
    first_text = ""
    async for token in run_stream(history):
        if token:
            first_text += token
            yield {"type": "token", "text": token}

    tool_data = _extract_tool_call(first_text)

    if tool_data:
        # Never send tool XML to speech. Execute silently and ask Hermes
        # for the final human-facing response.
        tool_output = await execute_tool_from_voice(tool_data)
        history.append({"role": "assistant", "content": first_text})
        history.append({
            "role": "system",
            "content": f"Tool output received:\n\n{tool_output}\n\nPlease generate your final response."
        })

        final_text = ""
        async for token in run_stream(history):
            if token:
                final_text += token
                yield {"type": "token", "text": token}

        final_text = re.sub(r"<tool_call>.*?</tool_call>", "", final_text, flags=re.S).strip()
        TOOL_HARNESS.save_memory(WEB_CHANNEL_ID, "local_owner_voice", "assistant", final_text)
        yield {"type": "done", "text": final_text}
        return

    clean_reply = re.sub(r"<tool_call>.*?</tool_call>", "", first_text, flags=re.S).strip()
    if not clean_reply:
        clean_reply = "Action completed successfully."

    TOOL_HARNESS.save_memory(WEB_CHANNEL_ID, "local_owner_voice", "assistant", clean_reply)
    yield {"type": "done", "text": clean_reply}


@app.post("/api/chat")
async def api_chat(payload: ChatPayload):
    reply = await execute_agent_logic(
        WEB_CHANNEL_ID,
        "local_owner_web",
        payload.message,
        is_owner=True,
        source="ui",
    )
    
    latest_staged = None
    if STAGED_ARTIFACTS:
        t_id, data = list(STAGED_ARTIFACTS.items())[-1]
        latest_staged = {
            "task_id": t_id,
            "filename": data["default_filename"],
            "mission": data["mission"]
        }
        
    return JSONResponse(content={"reply": reply, "staged_artifact": latest_staged})


@app.post("/api/voice/transcribe")
async def api_voice_transcribe():
    try:
        audio_bytes = await asyncio.to_thread(TOOL_HARNESS.record_voice)
        text = await asyncio.to_thread(TOOL_HARNESS.transcribe_voice, audio_bytes)
        return JSONResponse(content={"transcription": text})
    except Exception as e:
        print(f"❌ [Voice Transcription Error]: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})



@app.post("/api/voice/stream")
async def api_voice_stream(payload: ChatPayload):
    async def event_generator():
        # Collect sentences and send them to the persistent Oak TTS engine
        # sequentially. The model stream continues in parallel.
        speech_queue = asyncio.Queue()
        speech_done = object()
        tts_errors = []

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
        sentence_buffer = ""
        full_reply = ""

        try:
            async for event in voice_agent_stream(payload.message, True):
                if event["type"] == "token":
                    token = event["text"]
                    full_reply += token
                    sentence_buffer += token
                    yield f"data: {json.dumps({'type':'token','text':token})}\n\n"

                    sentences, sentence_buffer = _split_speech_sentences(sentence_buffer)
                    for sentence in sentences:
                        cleaned = clean_text_for_speech(sentence)
                        if cleaned:
                            await speech_queue.put(cleaned)

                elif event["type"] == "reply":
                    # Direct-action responses arrive complete.
                    reply = event["text"]
                    full_reply = reply
                    yield f"data: {json.dumps({'type':'token','text':reply})}\n\n"
                    cleaned = clean_text_for_speech(reply)
                    if cleaned:
                        await speech_queue.put(cleaned)

                elif event["type"] == "done":
                    if sentence_buffer.strip():
                        cleaned = clean_text_for_speech(sentence_buffer)
                        if cleaned:
                            await speech_queue.put(cleaned)

            await speech_queue.put(speech_done)
            await tts_task

            yield f"data: {json.dumps({'type':'done','reply':full_reply,'tts_error':tts_errors[0] if tts_errors else None})}\n\n"

        except Exception as exc:
            await speech_queue.put(speech_done)
            try:
                await tts_task
            except Exception:
                pass
            yield f"data: {json.dumps({'type':'error','error':str(exc)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/voice/listen")
async def api_voice_listen():
    try:
        # sounddevice is synchronous. Run the recorder in a worker thread so
        # the FastAPI event loop remains responsive to the dashboard, cron
        # scheduler, and other API requests while ARNIE is listening.
        audio_bytes = await asyncio.to_thread(TOOL_HARNESS.record_voice)
        text = await asyncio.to_thread(TOOL_HARNESS.transcribe_voice, audio_bytes)

        if not text:
            return JSONResponse(content={
                "reply": "I couldn't hear anything! Speak louder, soldier!",
                "transcription": ""
            })

        reply = await execute_agent_logic(
            WEB_CHANNEL_ID,
            "local_owner_voice",
            text,
            is_owner=True,
            source="voice",
        )
        return JSONResponse(content={"reply": reply, "transcription": text})
    except Exception as e:
        print(f"❌ [Voice API Error]: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/voice/speak")
async def api_voice_speak(payload: VoiceSpeakPayload):
    try:
        await asyncio.to_thread(speak_text_kokoro, payload.text)
        return JSONResponse(content={"status": "success"})
    except Exception as e:
        print(f"❌ [TTS Error]: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/cron/jobs")
async def get_cron_jobs():
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "next_run": str(job.next_run_time),
            "trigger": str(job.trigger)
        })
    return JSONResponse(content={"jobs": jobs})


@app.post("/api/memory/compact")
async def api_compact_memory():
    try:
        msg = await TOOL_HARNESS.compact_memory(WEB_CHANNEL_ID, keep_recent=5)
        return JSONResponse(content={"status": "success", "message": msg})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/vector/sync")
async def api_sync_vector_db():
    msg = sync_master_brain_vector_db()
    return JSONResponse(content={"status": "success", "message": msg})


@app.get("/api/swarm/staged")
async def get_staged_artifacts():
    return JSONResponse(content={"artifacts": STAGED_ARTIFACTS})


@app.post("/api/swarm/approve")
async def approve_staged_artifact(payload: ApprovalPayload):
    artifact = STAGED_ARTIFACTS.get(payload.task_id)
    if not artifact:
        return JSONResponse(status_code=404, content={"error": "Staged artifact not found or expired."})

    target_name = payload.target_filename or artifact["default_filename"]
    safe_name = re.sub(r'[\\/*?:"<>|]', "", target_name).strip()
    if not safe_name.endswith(".md") and not safe_name.endswith(".py"):
        safe_name += ".md"

    full_path = os.path.join(VAULT_DIR, safe_name)

    try:
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(artifact["content"])
            
        del STAGED_ARTIFACTS[payload.task_id]
        sync_master_brain_vector_db()
        print(f"💾 [Swarm Approval] Written to Master_Brain: {safe_name}")
        return JSONResponse(content={
            "status": "success",
            "message": f"APPROVED! Saved swarm output to {safe_name}",
            "filename": safe_name
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Failed disk commit: {str(e)}"})


@app.delete("/api/swarm/reject/{task_id}")
async def reject_staged_artifact(task_id: str):
    if task_id in STAGED_ARTIFACTS:
        del STAGED_ARTIFACTS[task_id]
        return JSONResponse(content={"status": "success", "message": "Artifact discarded from staging memory!"})
    return JSONResponse(status_code=404, content={"error": "Artifact ID missing."})


@app.post("/api/get_note")
async def api_get_note(payload: GetNotePayload):
    try:
        safe_name = re.sub(r'[\\/*?:"<>|]', "", payload.filename).strip()
        if not safe_name.endswith(".md"):
            safe_name += ".md"

        full_path = os.path.join(VAULT_DIR, safe_name)

        if not os.path.exists(full_path):
            return JSONResponse(
                status_code=404,
                content={"error": "File missing"},
            )

        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()

        return JSONResponse(content={"content": content})

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)},
        )


@app.post("/api/save_note")
async def api_save_note(payload: SaveNotePayload):
    try:
        safe_name = re.sub(r'[\\/*?:"<>|]', "", payload.filename).strip()
        if not safe_name.endswith(".md"):
            safe_name += ".md"

        full_path = os.path.join(VAULT_DIR, safe_name)

        with open(full_path, "w", encoding="utf-8") as f:
            f.write(payload.content)

        sync_master_brain_vector_db()
        print(f"💾 [Agentic OS] Saved structural update to file: {safe_name}")

        return JSONResponse(
            content={
                "status": "success",
                "message": f"Saved {safe_name}",
            }
        )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)},
        )


@app.get("/", response_class=FileResponse)
async def dashboard():
    index_path = os.path.join(
        os.path.dirname(__file__),
        "web",
        "index.html",
    )

    if not os.path.exists(index_path):
        return JSONResponse(
            status_code=404,
            content={"error": "web/index.html file missing."},
        )

    return FileResponse(index_path)


# 🔄 CONCURRENT RUNNER ENGINE (Standalone Capable)
async def main():
    init_cron_scheduler()
    sync_master_brain_vector_db()

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="warning",
    )
    server = uvicorn.Server(config)

    print(
        "\n🚀 [Agentic OS Core Initiated]"
        "\n🖥️  Web UI Chat Dashboard: http://127.0.0.1:8000"
    )

    DISCORD_BOT_TOKEN = ""  # Paste token here if using Discord, or leave empty!

    if DISCORD_BOT_TOKEN.strip():
        print("🤖 Connecting to Discord Gateway...")
        asyncio.create_task(client.start(DISCORD_BOT_TOKEN))
    else:
        print("⚡ LOCAL-ONLY MODE: Skipping Discord Gateway connection.")

    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())