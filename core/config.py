"""ARNIE AgenticOS runtime configuration.

Canonical home for AgenticOS persona and model-instruction configuration.
Interface adapters import these values; they do not define runtime behaviour.
"""

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
- If the user wants to see their tasks, list running tasks, check what ARNIE is working on, or ask about the task queue, call 'list_tasks'.
- If the user wants details, status, or output of a specific task by ID, call 'get_task'.
- If the user wants autonomous research on a topic, company, person, or lead, call 'run_agency_research'.
- If the user wants to research multiple topics at once, run parallel research tasks, or fan out agency work across several subjects simultaneously, call 'run_parallel_agency'.
- If the user wants to generate, create, or make an image from a description or prompt, call 'generate_image'.
- If the user wants to add, onboard, or register a new client or prospect, call 'add_client'.
- If the user wants to list, show, or check clients or the CRM, call 'list_clients'.
- If the user wants to update, move, or change a client's status, call 'update_client_status'.
- If the user wants to research a prospect, firm, or accountancy practice, call 'research_prospect'.
- If the user wants to list, show, or check prospects, call 'list_prospects'.
- If the user wants to get details on a specific prospect, call 'get_prospect'.
- If the user wants to draft outreach, write a cold email, or create a LinkedIn DM for a prospect, call 'draft_outreach'.
- If the user wants to log a savings baseline for a client process, call 'log_savings_baseline'.
- If the user wants to log an automation run or record time saved, call 'log_automation_run'.
- If the user wants to generate a monthly savings report or retainer invoice, call 'generate_savings_report'.
- If the user wants to see the client dashboard, pipeline overview, or MRR summary, call 'get_client_dashboard'.


To call a tool, respond ONLY with an XML block matching this exact format:
<tool_call>
{"name": "get_system_metrics", "arguments": {}}
</tool_call>
Do not add conversational text before or after the block. Absolute silence except for the tag!"""

DEFAULT_MODEL = "hermes3:8b"

# ─────────────────────────────────────────────────────────────────────────────
# Kaizen Studios outreach sender identity
# Update these when you have an email and website.
# ─────────────────────────────────────────────────────────────────────────────
KAIZEN_SENDER_NAME = "Kane"
KAIZEN_SENDER_TITLE = "Founder"
KAIZEN_SENDER_COMPANY = "Kaizen Studios"
KAIZEN_SENDER_EMAIL = ""        # not yet — leave blank, use LinkedIn CTA
KAIZEN_SENDER_LINKEDIN = ""     # add your LinkedIn profile URL when ready


# Optional second ModelProvider: any OpenAI-compatible inference server
# (LM Studio, vLLM, etc.). Left unset by default — the registry only
# registers it when OPENAI_COMPAT_HOST is configured.
OPENAI_COMPAT_ENABLED = False
OPENAI_COMPAT_PROVIDER_NAME = "lmstudio"
OPENAI_COMPAT_HOST = "http://127.0.0.1:1234/v1"
OPENAI_COMPAT_API_KEY = "not-needed"
OPENAI_COMPAT_MODEL = "local-model"

# Optional image generation provider: any Stable Diffusion-compatible API
# (Automatic1111, ComfyUI, etc.).  Disabled by default — the Harness only
# constructs ImageGenService when IMAGE_GEN_ENABLED is True.
IMAGE_GEN_ENABLED = False
IMAGE_GEN_HOST = "http://127.0.0.1:7860"
IMAGE_GEN_OUTPUT_DIR = "./media_output"
IMAGE_GEN_DEFAULT_STEPS = 20

# Discord voice: ARNIE speaks replies aloud in the user's voice channel.
# Requires PyNaCl and FFmpeg on PATH.  Off by default.
DISCORD_VOICE_ENABLED = False

# Memory injection: retrieve relevant Master Brain vault context and inject
# it into the system prompt so every conversation carries personal context.
MEMORY_INJECTION_ENABLED = True
MEMORY_INJECTION_TOP_K = 5
MEMORY_INJECTION_MIN_SCORE = 0.65

# Agent routing: pick a lighter local Ollama model for light workspaces
# when there is enough free VRAM headroom, instead of always using
# DEFAULT_MODEL. This codebase has no cloud provider — routing chooses
# between two local Ollama models, never a remote API.
OLLAMA_ENABLED = True
OLLAMA_HOST = "http://localhost:11434"
OLLAMA_LIGHT_MODEL = "phi3:mini"
OLLAMA_VRAM_HEADROOM_GB = 2.0
AGENT_ROUTING_ENABLED = True

# Parallel agency execution: cap on concurrent agency research tasks fanned
# out by run_parallel_agency via asyncio.gather().
PARALLEL_AGENCY_MAX_WORKERS = 4

# Per-turn memory injection: unlike MEMORY_INJECTION_* above (which only
# fires into the system prompt on the first turn of a conversation), this
# prepends a compact context block onto every subsequent user message so
# ARNIE stays grounded across a whole conversation, not just turn one.
MEMORY_PER_TURN_ENABLED = True
MEMORY_PER_TURN_TOP_K = 3
MEMORY_PER_TURN_MIN_SCORE = 0.68

