import discord
import json
import re
import os
import sys
import asyncio
import uvicorn
import subprocess
import uuid
import psutil
import random
import time
import io
import wave

from datetime import datetime
from ddgs import DDGS
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
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
from core.tools import ToolRisk
from core.agent_runtime import (
    AgentRuntime,
    ToolApprovalRequired as AgentRuntimeApprovalRequired,
)
from capabilities.voice import VoiceService
from capabilities.voice.oak import clean_text_for_speech, speak_text_kokoro
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
# 🕵️ PLAYWRIGHT STEALTH WEB SCRAPER
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0"
]

async def scrape_web_page_stealth(url: str, max_chars: int = 4000) -> str:
    print(f"🕷️ [Stealth Scraper] Initiating target bypass for: {url}")
    selected_user_agent = random.choice(USER_AGENTS)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-web-security",
                    "--no-sandbox",
                    "--disable-setuid-sandbox"
                ]
            )

            context = await browser.new_context(
                user_agent=selected_user_agent,
                viewport={"width": random.randint(1366, 1920), "height": random.randint(768, 1080)},
                locale="en-US",
                timezone_id="America/New_York"
            )

            page = await context.new_page()
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.navigator.chrome = { runtime: {} };
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
            """)

            await page.goto(url, wait_until="domcontentloaded", timeout=12000)
            await page.wait_for_timeout(1200)

            html_content = await page.content()
            await browser.close()

            soup = BeautifulSoup(html_content, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "svg", "iframe", "noscript"]):
                tag.decompose()

            text = soup.get_text(separator="\n").strip()
            clean_text = re.sub(r'\n{3,}', '\n\n', text)

            return clean_text[:max_chars]

    except Exception as e:
        return f"Stealth Scrape Failure ({url}): {str(e)}"


async def deep_research_web(query: str, crawl_top_n: int = 2) -> str:
    print(f"🔍 [Deep Researcher] Executing web search: {query}")
    try:
        with DDGS() as ddgs:
            results = [r for r in ddgs.text(query, max_results=5)]
            if not results:
                return "No search results found."

        research_report = f"# SEARCH RESULTS FOR: '{query}'\n\n"
        urls_to_scrape = []

        for idx, r in enumerate(results, start=1):
            title = r.get("title")
            url = r.get("href")
            snippet = r.get("body")
            research_report += f"### {idx}. {title}\n**URL:** {url}\n**Snippet:** {snippet}\n\n"
            if idx <= crawl_top_n and url:
                urls_to_scrape.append(url)

        if urls_to_scrape:
            research_report += "## DEEP PAGE CONTENT EXTRACTS\n\n"
            tasks = [scrape_web_page_stealth(u) for u in urls_to_scrape]
            scraped_pages = await asyncio.gather(*tasks)

            for u, content in zip(urls_to_scrape, scraped_pages):
                research_report += f"--- PAGE EXTRACT FROM: {u} ---\n{content}\n\n"

        return research_report
    except Exception as e:
        return f"Deep research failed: {str(e)}"


# ============================================================
# 📚 DAILY MASTER BRAIN VAULT SUMMARY
# ============================================================



# 🛠️ HARDWARE METRICS TELEMETRY ENGINE
def get_system_metrics_telemetry() -> str:
    print("⚡ [Agent Action] Pulling hardware system metrics telemetry...")
    try:
        cpu_load = psutil.cpu_percent(interval=0.3)
        cpu_count = psutil.cpu_count(logical=True)
        ram = psutil.virtual_memory()

        drive_letter = "G:\\" if os.path.exists("G:\\") else "C:\\"
        disk = psutil.disk_usage(drive_letter)

        ram_used_gb = ram.used / (1024**3)
        ram_total_gb = ram.total / (1024**3)
        disk_free_gb = disk.free / (1024**3)
        disk_total_gb = disk.total / (1024**3)
        process_count = len(psutil.pids())

        return (
            f"**ARNIE HARDWARE TELEMETRY REPORT**\n\n"
            f"⚡ **CPU Load:** `{cpu_load}%` ({cpu_count} Logical Cores)\n"
            f"🧠 **RAM Utilization:** `{ram.percent}%` ({ram_used_gb:.1f} GB / {ram_total_gb:.1f} GB)\n"
            f"💾 **Drive Space ({drive_letter}):** `{disk.percent}% Used` ({disk_free_gb:.1f} GB free of {disk_total_gb:.1f} GB)\n"
            f"⚙️ **Active OS Processes:** `{process_count}`\n"
            f"⏱️ **System Time:** `{datetime.now().strftime('%H:%M:%S')}`"
        )
    except Exception as e:
        return f"Telemetry Error: Unable to fetch kernel metrics: {str(e)}"


# 🛠️ AGENT TOOL SUITE
def perform_web_search(query: str) -> str:
    try:
        with DDGS() as ddgs:
            results = [r for r in ddgs.text(query, max_results=3)]
            if not results:
                return "No search results found."
            return "".join(
                [
                    f"Title: {r.get('title')}\nSnippet: {r.get('body')}\n\n"
                    for r in results
                ]
            )
    except Exception as e:
        return f"Error executing web search: {str(e)}"


def get_current_time() -> str:
    return (
        f"The current local system time is {datetime.now().strftime('%I:%M %p')} "
        f"and the date is {datetime.now().strftime('%A, %B %d, %Y')}."
    )






def run_terminal_command(command: str) -> str:
    print(f"⚡ [Agent Action] Executing system terminal command: {command}")
    dangerous_keywords = ["del", "rmdir", "format", "rm -rf", "shutdown", "registry"]
    if any(keyword in command.lower() for keyword in dangerous_keywords):
        return "Security Violation: This terminal command is blocked by the Agentic OS Kernel Sandbox."

    try:
        result = subprocess.run(
            command,
            shell=True,
            text=True,
            capture_output=True,
            timeout=10,
            cwd=r"G:\AgenticOS",
        )
        output = result.stdout.strip() if result.stdout else ""
        errors = result.stderr.strip() if result.stderr else ""

        if not output and not errors:
            return "Command executed successfully with zero console output text."
        if errors:
            return f"Windows Console Output:\n{output}\n\nConsole Error Log:\n{errors}"
        return f"Windows Console Output:\n{output}"
    except subprocess.TimeoutExpired:
        return "Process Error: Command execution timed out."
    except Exception as e:
        return f"Execution Failure: {str(e)}"


# 🐝 PHASE 3: MULTI-AGENT SWARM ORCHESTRATOR & STAGING BUFFER (8GB VRAM OPTIMIZED)
STAGED_ARTIFACTS = {}

class SubAgent:
    def __init__(self, name: str, system_prompt: str, model_name: str = "hermes3:8b"):
        self.name = name
        self.system_prompt = system_prompt
        self.model_name = model_name

    async def run_task(self, task_description: str) -> str:
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": task_description}
        ]
        capability = (
            "research"
            if self.name.lower() == "researcher"
            else "coding"
            if self.name.lower() == "coder"
            else "reasoning"
        )

        return await arnie_model_chat(
            messages,
            model=self.model_name,
            capability=capability,
        )


class SwarmManager:
    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries
        self.agents = {
            "researcher": SubAgent(
                "Researcher",
                "You are a Lead Technical Researcher. Synthesize web documentation, code specs, and API structures into clean architecture plans.",
                model_name="hermes3:8b"
            ),
            "coder": SubAgent(
                "Coder",
                "You are an expert developer. Produce clean, complete, working Python/JS code block based on research specifications. Do NOT include conversation.",
                model_name="qwen2.5-coder:7b"
            ),
            "reviewer": SubAgent(
                "Reviewer",
                """You are a strict code auditor and security checker. Analyze the code provided.
Respond ONLY in valid JSON matching this exact structure:
{
  "passed": true | false,
  "issues": ["list of specific bugs, security flags, or missing imports"],
  "feedback": "Detailed instructions for the Coder on how to fix the issues"
}
Do not include markdown wrappers outside the JSON block!""",
                model_name="phi4-mini"
            )
        }

    async def _audit_code(self, code_content: str) -> dict:
        review_raw = await self.agents["reviewer"].run_task(f"Review this code:\n\n{code_content}")
        clean_json = re.sub(r"```(?:json)?", "", review_raw).strip("` \n")

        try:
            return json.loads(clean_json)
        except Exception:
            passed = "passed: true" in review_raw.lower() or "no issues" in review_raw.lower()
            return {
                "passed": passed,
                "issues": ["Could not parse structured JSON review format."],
                "feedback": review_raw
            }

    async def _test_code_in_sandbox(self, code_content: str) -> dict:
        if "def " not in code_content and "import " not in code_content and "print(" not in code_content:
            return {"executed": False, "passed": True, "output": "Non-executable script or documentation block."}

        clean_code = re.sub(r"```(?:python)?", "", code_content).strip("` \n")
        sandbox_dir = r"G:\AgenticOS\data"
        os.makedirs(sandbox_dir, exist_ok=True)
        temp_file_path = os.path.join(sandbox_dir, f"sandbox_{uuid.uuid4().hex[:8]}.py")

        try:
            with open(temp_file_path, "w", encoding="utf-8") as temp_file:
                temp_file.write(clean_code)

            result = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, temp_file_path],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=sandbox_dir
            )

            stdout = result.stdout.strip()
            stderr = result.stderr.strip()

            if result.returncode == 0:
                return {
                    "executed": True,
                    "passed": True,
                    "output": stdout or "Executed with 0 errors (No print output)."
                }
            else:
                return {
                    "executed": True,
                    "passed": False,
                    "output": f"RUNTIME EXCEPTION (Exit Code {result.returncode}):\n{stderr}"
                }

        except subprocess.TimeoutExpired:
            return {
                "executed": True,
                "passed": False,
                "output": "RUNTIME TIMEOUT EXCEPTION: Code execution exceeded 5-second limit."
            }
        except Exception as e:
            return {
                "executed": True,
                "passed": False,
                "output": f"SANDBOX FAILURE: {str(e)}"
            }
        finally:
            if os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except Exception:
                    pass

    async def execute_crew_pipeline(self, mission_prompt: str) -> dict:
        print(f"\n🚀 [Swarm Engine] Deep Mission Initiated: '{mission_prompt}'")

        raw_web_data = await deep_research_web(mission_prompt, crawl_top_n=2)
        researcher_input = (
            f"USER MISSION: {mission_prompt}\n\n"
            f"LIVE DEEP WEB SCRAPE DATA:\n{raw_web_data}\n\n"
            f"Task: Synthesize technical specifications and clean code architecture based on the live web data above."
        )

        research_out = await self.agents["researcher"].run_task(researcher_input)

        current_code = ""
        last_feedback = ""
        attempt_logs = []
        is_approved = False

        for attempt in range(1, self.max_retries + 1):
            print(f"💻 [Swarm] Phase 2 (Attempt {attempt}/{self.max_retries}): Generating Code...")

            if attempt == 1:
                coder_prompt = f"Mission: {mission_prompt}\nArchitectural Specs:\n{research_out}"
            else:
                coder_prompt = (
                    f"Mission: {mission_prompt}\n\n"
                    f"YOUR PREVIOUS CODE FAILED TESTING. FIX THESE BUGS IMMEDIATELY:\n"
                    f"{last_feedback}\n\n"
                    f"Previous Code:\n{current_code}"
                )

            current_code = await self.agents["coder"].run_task(coder_prompt)

            print(f"🧐 [Swarm] Phase 3A: Reviewer Static Audit...")
            audit_result = await self._audit_code(current_code)

            if not audit_result.get("passed", False):
                last_feedback = f"STATIC AUDIT FAILURE:\n{audit_result.get('feedback')}"
                attempt_logs.append({
                    "attempt": attempt, "stage": "Audit", "passed": False, "feedback": last_feedback
                })
                print(f"⚠️ Static Audit Failed on attempt {attempt}")
                continue

            print(f"🧪 [Swarm] Phase 3B: Running Subprocess Sandbox Test...")
            sandbox_result = await self._test_code_in_sandbox(current_code)

            if not sandbox_result.get("passed", False):
                last_feedback = f"SANDBOX EXECUTION FAILURE:\n{sandbox_result.get('output')}"
                attempt_logs.append({
                    "attempt": attempt, "stage": "Sandbox", "passed": False, "feedback": last_feedback
                })
                print(f"❌ Sandbox Execution Failed on attempt {attempt}")
                continue

            print(f"✅ [Swarm] AUDIT & SANDBOX EXECUTION PASSED ON ATTEMPT {attempt}!")
            is_approved = True
            attempt_logs.append({
                "attempt": attempt, "stage": "Sandbox", "passed": True, "feedback": sandbox_result.get('output')
            })
            break

        task_id = str(uuid.uuid4())
        safe_mission_name = re.sub(r'[^a-zA-Z0-9]', '_', mission_prompt[:20]).strip("_")
        default_filename = f"Swarm_{safe_mission_name}.md"

        audit_history_md = ""
        for log in attempt_logs:
            status_icon = "✅ PASSED" if log["passed"] else "❌ FAILED"
            audit_history_md += f"- **Pass {log['attempt']} ({log['stage']})**: {status_icon}\n  *Log*: {log['feedback']}\n\n"

        full_content = (
            f"# SWARM MISSION: {mission_prompt}\n\n"
            f"**SANDBOX TEST STATUS:** {'PASSED' if is_approved else 'STAGED WITH ERRORS'}\n"
            f"**TOTAL PASSES:** {len(attempt_logs)} / {self.max_retries}\n\n"
            f"## 1. ARCHITECTURAL SPECIFICATIONS\n{research_out}\n\n"
            f"## 2. TESTED CODE\n{current_code}\n\n"
            f"## 3. AUDIT & SANDBOX LOGS\n{audit_history_md}"
        )

        STAGED_ARTIFACTS[task_id] = {
            "content": full_content,
            "default_filename": default_filename,
            "mission": mission_prompt,
            "status": "AWAITING_APPROVAL",
            "is_approved": is_approved
        }

        return {
            "task_id": task_id,
            "default_filename": default_filename,
            "is_approved": is_approved,
            "code": current_code,
            "full_content": full_content
        }

swarm_orchestrator = SwarmManager(max_retries=3)


def launch_swarm_task(mission: str) -> str:
    loop = asyncio.get_event_loop()
    res = loop.run_until_complete(swarm_orchestrator.execute_crew_pipeline(mission))
    return (
        f"SWARM PIPELINE COMPLETE!\nTask ID: {res['task_id']}\n"
        f"Artifact staged in memory. Open Web Dashboard to approve writing '{res['default_filename']}' to G:\\Master_Brain."
    )


# ⏰ AUTONOMOUS CRON SCHEDULER JOBS
async def scheduled_vault_summary_job():
    print("⏰ [Cron Engine] Executing Daily Master Brain Vault Summary & Vector Sync Job...")
    try:
        sync_master_brain_vector_db()
        files = [f for f in os.listdir(VAULT_DIR) if f.endswith(".md")]
        file_summary = f"Total Markdown Files in Vault: {len(files)}\n" + "\n".join([f"- {f}" for f in files[:10]])

        mission = f"Synthesize a daily executive summary report for Master Brain vault.\nVault Context:\n{file_summary}"
        await swarm_orchestrator.execute_crew_pipeline(mission)
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


# Core owns chat and tool orchestration; this module only adapts interfaces.
AGENT_RUNTIME = AgentRuntime(
    harness=TOOL_HARNESS,
    tool_registry=TOOL_REGISTRY,
    intent_router=INTENT_ROUTER,
    model_chat=arnie_model_chat,
    metrics_provider=get_system_metrics_telemetry,
    base_system_prompt=BASE_SYSTEM_PROMPT,
    owner_extensions=OWNER_EXTENSIONS,
    privileged_risk=ToolRisk.PRIVILEGED,
)

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
            result = await AGENT_RUNTIME.execute_tool(
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
            reply = await AGENT_RUNTIME.execute(
                message.channel.id,
                message.author.id,
                clean_content,
                is_owner,
                source="discord",
            )
            await message.reply(reply)
        except AgentRuntimeApprovalRequired as approval:
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
        return await AGENT_RUNTIME.execute_tool(
            tool_name,
            args,
            source="voice",
        )
    except AgentRuntimeApprovalRequired as approval:
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

            tool_output = await AGENT_RUNTIME.execute_tool(
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
        reply = await AGENT_RUNTIME.execute(
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
    reply = await AGENT_RUNTIME.execute(
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

        reply = await AGENT_RUNTIME.execute(
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
