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
| 8 | Persistent Task queue (survive restart, queue depth) | 🔜 Next |

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
| `api.py` | FastAPI endpoints (277 lines) |
| `web/index.html` | Dashboard — task panel, events, system health |

---

## Canonical tools (12)

**Wave 1 — safe, read-only:**
`web_search`, `get_current_time`, `read_obsidian_note`, `search_vault`,
`get_daily_vault_summary`, `get_system_metrics`, `list_tasks`, `get_task`

**Wave 2 — privileged, state-mutating:**
`launch_app`, `write_obsidian_note`, `run_terminal_command`, `launch_swarm`

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
