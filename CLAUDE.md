# ARNIE — AgenticOS · Claude Code Project Context

## What this is

ARNIE is a local-first Agentic Operating System running as a Discord bot + FastAPI
web dashboard. The persona is Arnold Schwarzenegger. The architecture is not.

The goal is a properly layered orchestration platform, migrated incrementally from
a legacy `bot.py` monolith. Every session should leave the architecture more real,
not just the tests greener.

---

## Canonical dependency direction

```
Interface  (bot.py, api.py, web/)
    ↓
AgentRuntime  (core/agent_runtime.py)
    ↓
AgentHarness  (core/harness.py)
    ↓
PolicyEngine  (core/policy.py)
    ↓
ToolRegistry  (core/tools.py)
    ↓
Capability  (capabilities/)
```

`core/` and `capabilities/` must never import from interface modules.
`bot.py` is the composition root and Discord interface only.

---

## Architecture phases — status

| Phase | Work | Status |
|---|---|---|
| 1 | Task, Agent, Tool, Event domain objects | ✅ Done |
| 2 | ModelProvider abstraction (OllamaProvider) | ✅ Done |
| 3 | SQLite-backed TaskStore, real Task lifecycle | ✅ Done |
| 4 | Task Queue dashboard panel (live, filtered, auto-refresh) | ✅ Done |
| 5 | Memory interface (SQLite/ChromaDB/Brain behind service boundary) | ✅ Done |
| 6 | Voice extraction | ✅ Done |
| 7 | Interface thinning (bot.py / api.py further cleanup) | ✅ Done |
| 8 | Persistent Task queue (survive restart, queue depth) | ✅ Done |
| 9 | Swarm missions tracked as first-class Tasks (workspace="swarm") | ✅ Done |
| 10 | Live Event Stream dashboard (SSE from EventBus) | ✅ Done |
| 11 | OpenAICompatibleProvider (LM Studio / vLLM support) | ✅ Done |
| 12 | Agency workspace — run_agency_research Tool (workspace="agency") | ✅ Done |
| 12 | Agency workspace — run_agency_research Tool (workspace="agency" Tasks) | ✅ Done |
| 13 | Media workspace — generate_image Tool (workspace="media" Tasks) | ✅ Done |
| 14 | System prompt + intent router completeness (all 13 tools reachable from Discord) | ✅ Done |
| 15 | Discord Voice — ARNIE speaks replies in voice channel via Kokoro TTS | ✅ Done |
| 16 | Dashboard mothership redesign — 3-column layout, live metrics, always-on tasks + events, vault today (Phase 16) | ✅ Done |
| 17 | Memory injection — vault context retrieved via Ollama embeddings, injected into system prompt | ✅ Done |
| 18 | Agent routing + Ollama load balancing — VRAM-aware model selection | ✅ Done |
| 19 | Client workspace — CRM tools for tracking agency clients | ✅ Done |
| 20 | Parallel agency execution — run_parallel_agency fans out concurrent research | ✅ Done |
| 21 | Dashboard 2.0 (particle neural net centre, micro-apps panel, YouTube Studio widget, agent status feed) | ✅ Done |
| 22 | Bot token moved out of bot.py into .env / secrets manager | ✅ Done |
| 23 | Per-turn memory injection (currently first-turn only) | ✅ Done |

---

## Key files

| File | Role |
|---|---|
| `core/harness.py` | Central orchestration — agent selection, model routing, policy, tool execution, swarm, memory, voice, events |
| `core/agent_runtime.py` | Conversational orchestration — intent → tool → response loop |
| `core/policy.py` | PolicyEngine — ALLOW / APPROVAL_REQUIRED / DENY |
| `core/tools.py` | ToolRegistry — 12 canonical tools |
| `core/tasks.py` | Task domain object + lifecycle |
| `core/agents.py` | Agent definitions (Coordinator, Researcher, Coder, Reviewer) |
| `core/models.py` | ModelProvider Protocol, OllamaProvider, ModelRegistry |
| `core/config.py` | DEFAULT_MODEL, BASE_SYSTEM_PROMPT, OWNER_EXTENSIONS |
| `core/scheduler.py` | Timing only — no business logic |
| `core/events.py` | EventBus |
| `core/intent.py` | IntentRouter — deterministic first-pass routing |
| `core/swarm.py` | SwarmManager |
| `capabilities/tasks/service.py` | TaskStore — SQLite persistence |
| `bot.py` | Discord interface + composition root (288 lines) |
| `api.py` | FastAPI endpoints, incl. GET /api/events (SSE) |
| `web/index.html` | Dashboard — task panel, live event stream, system health |

---

## Canonical tools (12)

**Wave 1 — safe, read-only:**
`web_search`, `get_current_time`, `read_obsidian_note`, `search_vault`,
`get_daily_vault_summary`, `get_system_metrics`, `list_tasks`, `get_task`

**Wave 2 — privileged, state-mutating:**
`launch_app`, `write_obsidian_note`, `run_terminal_command`, `launch_swarm`,
`run_agency_research`, `generate_image`

Wave-2 tools auto-approve from `ui` source; require human approval from `discord`.

---

## PolicyEngine decision flow

```
ALLOW            → execute immediately
APPROVAL_REQUIRED → raise ToolApprovalRequired (runtime handles)
DENY             → raise PermissionError
```

`_authorize_tool` raises `PermissionError` only on `DENY`.
`AgentRuntime.execute_intent_tool()` converts `APPROVAL_REQUIRED` → `ToolApprovalRequired`.

---

## Model defaults

`DEFAULT_MODEL = "hermes3:8b"` defined in `core/config.py`.
`Harness.select_model_provider()` returns the first registered provider — no hardcoded
provider name anywhere in `core/`.

---

## Validation suite — run before every commit

```powershell
python -m core.test_architecture
python -m core.test_execution_boundary
python -m core.test_agent_runtime
python -m core.test_source_approval
python -m core.harness
```

All five must be green. Architecture contract test is the canonical boundary enforcer.

---

## Working style (Kane has ADHD)

- One coherent architectural change per session. Validate. Commit. Move on.
- Surgical edits only — never regenerate a large file from memory.
- When modifying a file: read the exact text first, patch with Python str.replace or
  sed, verify the patch landed, run tests.
- Never alter encoding, line endings, or unrelated content.
- Provide exact PowerShell commands to run.
- Do not make changes to already-green areas.
- Do not commit until the full diff is reviewed.
- The `.gitattributes` enforces LF — no CRLF noise.

---

## Git baseline

```
1ca9780 feat(web): live EventBus stream on the dashboard (Phase 10)
8ea6ea5 docs: mark Phase 9 done, update git baseline
3dcc6e4 arch: track Swarm missions as first-class Tasks (Phase 9)
0a25d21 docs: mark Phase 8 done, update git baseline
d210513 arch: recover interrupted Tasks on Harness startup (Phase 8)
7c920c4 docs: mark Phase 7 done, advance Phase 8 to next, update git baseline
57d8336 arch: move Swarm staging/approval logic out of api.py (Phase 7)
f309b9e  arch: voice boundary — VoiceService.speak + Harness facades + fix http adapter
e53137f  docs: mark Phase 5 done, advance Phase 6 to next, update git baseline
4d3b6cb  arch: bot.py uses Harness memory/task facade, not internal stores
6ffbe5e  docs: add CLAUDE.md project context + gitignore IJFW scaffolding
afb35b4  feat(web): add live Task Queue panel to dashboard
1746310  arch: add list_tasks/get_task as canonical conversational Tools
c27db31  chore: remove dead legacy bot_memory files
dda09f3  arch: Task read path, periodic cleanup job, fix stale runtime test
9dadb12  arch: SQLite-backed TaskStore, Harness-driven Task lifecycle
8f1f258  arch: remove provider name string from Harness
30f2163  arch: execution boundary contract + CRLF normalisation
```

---

## What NOT to do

- Do not regenerate `core/harness.py` from memory — it is 1 300+ lines.
- Do not alter PolicyEngine, AgentRuntime, or ToolRegistry to make tests pass.
- Do not hardcode `"ollama"` or any provider name in `core/`.
- Do not store critical workflow state only in process memory.
- Do not commit until `git diff --cached --stat` has been reviewed.
- Do not skip the validation suite before committing.
### Phase 17 — Memory Injection (`c381a8d`)
- `core/config.py`: added MEMORY_INJECTION_ENABLED, TOP_K=5, MIN_SCORE=0.65
- `capabilities/vault/service.py`: added retrieve_relevant() using Ollama embeddings to match existing index space
- `core/agent_runtime.py`: injects [MEMORY CONTEXT] block into system prompt on first turn of each conversation
- Verified live end-to-end: real ChromaDB matches confirmed in LLM system prompt
### Phase 18 — Agent Routing + Ollama Load Balancing (`29e9e9d`)
- `core/config.py`: added OLLAMA_ENABLED, OLLAMA_LIGHT_MODEL=phi3:mini, OLLAMA_VRAM_HEADROOM_GB=2.0, AGENT_ROUTING_ENABLED
- `core/model_router.py`: new file — routes workspace to hermes3:8b (default) or phi3:mini (light) based on live VRAM headroom via Ollama /api/ps; no cloud branch (codebase is local-only)
- `core/agents.py`: added get_system_prompt_for_workspace() using existing find_by_name() — AgentRegistry._agents is keyed by ID not name
- `core/agent_runtime.py`: Coordinator agent system prompt prepended before BASE_SYSTEM_PROMPT; model swap applied to plain-conversation LLM call only (not tool-synthesis calls)
- Verified live: VRAM tracking correctly demotes routing when hermes3:8b loaded (1.4GB free < 2.0GB threshold)
### Phase 19 — Client Workspace + CRM (`62f31d4`)
- `core/tasks.py`: added client to workspace literals
- `core/policy.py`: added WorkspacePolicy for client workspace
- `capabilities/clients/service.py`: JSON-backed Client store (add/list/update)
- `core/tools.py`: add_client, list_clients, update_client_status tools
- `core/harness.py`: execute_* methods with full Task lifecycle for mutating tools, lightweight read for list_clients
- `core/config.py`: OWNER_EXTENSIONS guidance for all three tools
- `core/intent.py`: deterministic routes for list clients + add client
- `clients.json` added to .gitignore (runtime data)
- Verified: Discord requires approval for update_client_status, UI auto-approves; Task lifecycle queryable via list_tasks(workspace=client)
### Phase 20 — Parallel Agency Execution
- `core/config.py`: PARALLEL_AGENCY_MAX_WORKERS=4, OWNER_EXTENSIONS updated
- `core/harness.py`: execute_run_parallel_agency() — asyncio.gather() over execute_agency_research(), per-topic exception isolation, each sub-task gets own workspace=agency Task
- `core/tools.py`: run_parallel_agency registered as CONTROLLED, stub + expected sets updated
- `core/intent.py`: deterministic route for parallel/fan-out phrasing, placed before single-topic agency_match
- Verified live: two sub-tasks interleaved (real concurrency confirmed), each Task queryable, results merged into one report
### Phase 22 — Bot Token Out of bot.py (`bfaf7a3`)
- `bot.py`: DISCORD_BOT_TOKEN now read via `os.environ.get("DISCORD_BOT_TOKEN", "")` with `python-dotenv` loading `.env` at import time; empty/missing token still falls through to LOCAL-ONLY MODE
- `.env.example` added documenting the expected key; `.env` already covered by `.gitignore`
- Trigger: a real token had been pasted directly into bot.py in a prior uncommitted local edit — confirmed via full `git log --all -p` scan that it was never pushed to GitHub, then stripped before any commit
### Phase 21 — Dashboard 2.0 (`c7ffc54`)
- `web/index.html`: full rewrite to Rubric-style dark mothership — orange/amber design system, 3-column layout, header, floating swarm approval modal unchanged
- Added animated particle canvas (`#particleCanvas`, pure JS, no libraries) — 80 nodes colour-coded by workspace, edges within 120px, idle breathing effect, pulses on live SSE events
- Added Agent Status panel (hermes3:8b/phi3:mini rows + system RAM bar — no live VRAM/routing endpoint exists yet, so RAM is the load proxy), YouTube Studio panel (placeholder tiles — no `/api/youtube` endpoint), Client CRM panel (reads `/api/tasks?workspace=client` — no dedicated `/api/clients` endpoint)
- Every existing JS function preserved verbatim by element ID: chat, voice pipeline, SSE stream, vault preview/quick capture, swarm approval, cron/RAG/memory buttons — zero behavior regressions
- No external CDN dependencies; Google Fonts import removed in favour of a local monospace stack
- Verified live: launched via `python bot.py`, Playwright screenshot confirmed correct render with no console errors beyond the expected `/api/youtube` 404; `/api/chat` smoke-tested end-to-end through the real Harness/Ollama pipeline; fixed two panel-height overflow bugs found in the first screenshot pass (Quick Capture save button, Agent Status RAM bar)
### Phase 23 — Per-Turn Memory Injection (`0c2d0a3`)
- `core/config.py`: MEMORY_PER_TURN_ENABLED=True, MEMORY_PER_TURN_TOP_K=3, MEMORY_PER_TURN_MIN_SCORE=0.68 (tighter than Phase 17's first-turn top_k=5/min_score=0.65 since this runs every turn)
- `core/agent_runtime.py`: `execute()` now computes `_is_first_turn = not history` before the Phase 17 system-prompt block (replaces the old inline `if not history:` check); a new block prepends a compact `[CONTEXT: ...]` prefix onto the in-memory `history` entry for every turn after the first, via `retrieve_relevant()` (same import pattern as Phase 17, since `VaultService` doesn't exist as a class — `capabilities/vault/service.py` only exposes module-level functions)
- `harness.save_memory()` still persists the raw, unprefixed `clean_content` — only the transient LLM-facing `history` list carries the prefix, so the stored conversation memory never gets polluted with injected context
- Best-effort: any `retrieve_relevant` failure silently falls back to the original message, never blocking the response path
- Verified live: a two-turn conversation on a fresh channel (via a `harness.chat` spy, since the persisted store never shows the transient prefix) confirmed no injection on turn 1, `retrieve_relevant` called with the configured top_k/min_score on turn 2, the model actually received the `[CONTEXT:]`-prefixed message on turn 2, and the persisted store stayed unprefixed throughout
### Phase 23 — Per-Turn Memory Injection
- `core/config.py`: MEMORY_PER_TURN_ENABLED, TOP_K=3, MIN_SCORE=0.68
- `core/agent_runtime.py`: compact [CONTEXT: ...] prefix prepended to user message (clean_content) on all turns except first; guard prevents double-injection on turn 1
- Uses module-level retrieve_relevant() from capabilities/vault — no VaultService class exists
- Verified: turn 2+ carries memory prefix, memory store stays unpolluted (stores raw clean_content)

### Phase 24 — Lead Research Engine (Kaizen Studios)
- `capabilities/prospects/__init__.py` + `capabilities/prospects/service.py`: new Prospect dataclass (id, firm_name, website, staff_count, services, software_stack, pain_signals, priority, status, researched_at, notes, outreach_email, outreach_dm); JSON-backed store at `prospects.json`; CRUD: `add_prospect`, `list_prospects`, `get_prospect`, `update_prospect_status`
- `core/tools.py`: added Prospect workspace to module docstring; 3 stub handlers (`_research_prospect`, `_list_prospects`, `_get_prospect`); 3 Tool registrations (phase=24, workspace="prospects", handler_bound_by="AgentHarness")
- `core/harness.py`: 3 `bind_handler` calls for prospect tools; `execute_research_prospect` (runs `deep_research_web` + 2× `web_search`, heuristic extraction of software stack and pain signals, stores Prospect via capability); `execute_list_prospects`; `execute_get_prospect`
- `.gitignore`: `prospects.json` excluded (runtime data, same as `clients.json`)
- Architecture: same workspace/Task tracking pattern as Phase 19 (client workspace) — research mission tracked as `workspace="prospects"` Task, Harness owns persistence, capability layer never touches Tool registry directly

### Phase 25 — Outreach Drafting Engine (Kaizen Studios)
- `capabilities/prospects/service.py`: added `save_outreach(prospect_id, outreach_email, outreach_dm)` — updates `outreach_email` and `outreach_dm` fields on an existing Prospect record
- `capabilities/prospects/__init__.py`: exports `save_outreach`
- `core/tools.py`: `_draft_outreach` stub handler; `draft_outreach` Tool registered (phase=25, workspace="outreach", risk=CONTROLLED, synthesis_required=True)
- `core/harness.py`: `bind_handler("draft_outreach", self.execute_draft_outreach)`; `execute_draft_outreach` — loads Prospect, builds ARNIE system prompt (Kaizen Studios offer, tone, word limits), calls `self.chat()` with prospect profile as user message, parses `=== EMAIL SUBJECT === / === EMAIL BODY === / === LINKEDIN DM ===` delimiters, stores drafts via `save_outreach`, returns formatted drafts for review
- Note: ARNIE is the lead agent of Kaizen OS — system prompt established this identity for all outreach generation

### Workspace Routing Wired Into select_agent() (`eecdabd`)
- `core/agents.py`: extracted the workspace->agent mapping into module-level `WORKSPACE_AGENT_NAMES`; added `AgentRegistry.find_by_workspace()`; `get_system_prompt_for_workspace()` now delegates to it instead of holding its own copy of the mapping
- `core/harness.py`: `select_agent()` now consults `find_by_workspace(task.workspace)` between the metadata-agent check and the Coordinator fallback — previously every Task fell through to Coordinator regardless of workspace
- Routing: prospects→Scout, outreach→Pitch, client→Atlas, development→Forge, agency→Researcher, swarm/personal/system/media stay on Coordinator
- Also fixed a pre-existing SyntaxError in `execute_research_prospect` (literal newlines inside f-strings instead of `\n`) that was blocking `core/harness.py` from importing at all — landed as its own commit (`e05376a`) ahead of the routing change
- Verified live: `core.harness` smoke-test task (`workspace="development"`) now resolves to Forge/qwen2.5-coder:7b instead of always defaulting to Coordinator/hermes3:8b
- Two further bugs surfaced by wiring routing live, both fixed as their own commits:
  - `execute_draft_outreach`'s `self.chat()` call omitted `model=`, so once workspace routing was live it silently inherited Forge's `qwen2.5-coder:7b` (a coding model) via `self.chat()`'s hardcoded internal `workspace="development"` Task — pinned to `model=DEFAULT_MODEL` (`75e1348`)
  - `core/policy.py`'s default workspace policies never included `"prospects"` or `"outreach"` — `PolicyEngine.evaluate()` DENYs any workspace with no registered policy, so every Phase 24/25 tool call (`research_prospect`, `list_prospects`, `get_prospect`, `draft_outreach`) was being denied in practice. Registered both, matching the `agency`/`development` policy shape (`668b181`)
- Also fixed `python -m core.tools` — its self-test's expected registry-name set was never updated for Phase 24/25's four tools, so it had been failing since those phases shipped (`79eea8b`)

### Phase 26 — Savings Baseline Logger (`3a1fb40`)
- `capabilities/savings/__init__.py` + `capabilities/savings/service.py`: new SavingsBaseline dataclass (id, client_id, process_name, minutes_per_run, runs_per_month, staff_hourly_rate, baseline_monthly_cost, logged_at, notes); JSON-backed store at `savings_baselines.json`; `log_baseline` computes `baseline_monthly_cost = (minutes_per_run * runs_per_month / 60) * staff_hourly_rate`; `list_baselines`, `get_baseline`
- `core/tools.py`: `log_savings_baseline` (CONTROLLED, mutates_state=True) + `list_savings_baselines` (SAFE), both deterministic/direct-mode, workspace="client", phase=26
- `core/harness.py`: `execute_log_savings_baseline` / `execute_list_savings_baselines` — same Task-lifecycle pattern as `execute_add_client`/`execute_list_clients`
- `core/agents.py`: Atlas granted `log_savings_baseline` + `list_savings_baselines` — PolicyEngine denies unpermitted agents regardless of correct workspace routing, so this step is required, not optional
- `.gitignore`: `savings_baselines.json` + `automation_runs.json` (Phase 27, added ahead of building it)
- Verified live end-to-end: `workspace="client"` Task resolves to Atlas, PolicyEngine ALLOWs, a real baseline computed correctly (45 min/run × 20 runs/mo @ £18.50/hr = £277.50/mo) and listed back
