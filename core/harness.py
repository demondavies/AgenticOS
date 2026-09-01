"""
ARNIE Agentic OS
Agent Harness

This is the first working orchestration layer.

The Harness coordinates:

    Task
      ↓
    Agent
      ↓
    Model Provider
      ↓
    Model
      ↓
    Result
      ↓
    Events

IMPORTANT:

This is deliberately a SMALL first implementation.

It does not yet:
    - replace bot.py
    - persist tasks
    - execute arbitrary tools without Policy authorization
    - manage the swarm outside the canonical Tool boundary
    - manage Discord
    - manage FastAPI
    - manage voice
    - manage Master Brain

Those systems will be migrated onto the Harness incrementally.

The purpose of this module is to prove the central architectural loop.
"""

from __future__ import annotations

import asyncio

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .config import DEFAULT_MODEL

from .agents import (
    Agent,
    AgentRegistry,
    AgentStatus,
    create_default_agent_registry,
)

from .events import (
    Event,
    EventBus,
    EventCategory,
    EventNames,
    EventSeverity,
    create_event,
)

from .models import (
    ModelMessage,
    ModelProvider,
    ModelRegistry,
    ModelRequest,
    ModelResponse,
    create_default_model_registry,
)

from .tasks import (
    Task,
    TaskExecution,
    TaskResult,
    TaskStatus,
)

from .tools import (
    ToolRegistry,
    create_default_registry,
)

from .policy import (
    PolicyDecision,
    PolicyEngine,
    PolicyRequest,
)

from capabilities.memory import (
    MemoryStore,
)
from capabilities.tasks import TaskStore
from capabilities.voice import VoiceService
from capabilities.web.research import deep_research_web
from .swarm import SwarmManager


# ============================================================================
# PROSPECT DISCOVERY — directory/aggregator domains to exclude
# ============================================================================
#
# UK local-business searches (e.g. "accountant Barnstaple") are dominated by
# directory and aggregator sites rather than the firms themselves. This list
# is used both to build `-site:` exclusions on the DuckDuckGo query (so real
# firm results aren't crowded out of the top N) and, as a fallback, to filter
# any that slip through post-search.
DISCOVERY_DIRECTORY_DOMAINS = [
    "yell.com", "bark.com", "checkatrade.com", "freeindex.co.uk",
    "thomsonlocal.com", "ratedpeople.com", "trustatrader.com",
    "yelp.com", "unbiased.co.uk", "vouchedfor.co.uk",
    "accountantsup.co.uk", "ukaccountingfirms.co.uk",
    "icaew.com", "find.icaew.com", "countingup.com", "sage.com",
    "cylex-uk.co.uk", "hotfrog.co.uk", "misterwhat.co.uk",
    "192.com", "scoot.co.uk", "brownbook.net", "thebestof.co.uk",
    "approvedaccountants.co.uk", "enrollbusiness.com",
    "businessprofilepages.com", "yalwa.co.uk",
    "finacbooks.co.uk", "mhc-accountant.co.uk",
    "serviceprofessionals.co.uk", "holsworthy.cylex-uk.co.uk",
    "my-towns.co.uk", "barronco.com", "accountingandmorect.com",
    "accountantwarwickshire.co.uk", "charteredaccountantlondon.co.uk",
    "taxrpo.com", "here4business.uk",
    # Additional directory/aggregator sites found in prospect data
    "chamberofcommerce.uk", "chamberofcommerce.com",
    "simplyhired.co.uk", "simplyhired.com",
    "surreyaccountantsdirectory.co.uk", "accountingfirms.co.uk",
    "i24app.com", "aboutbridgnorth.com", "discoverhuntingdon.co.uk",
    "adzuna.co.uk", "reed.co.uk", "totaljobs.com", "indeed.co.uk",
    "glassdoor.co.uk", "cv-library.co.uk", "monster.co.uk",
    "locallife.co.uk", "uksmallbusinessdirectory.com",
    "bizify.co.uk", "approved.co.uk",
]

DISCOVERY_SOCIAL_GOV_DOMAINS = [
    "linkedin.com", "uk.linkedin.com", "facebook.com", "twitter.com",
    "instagram.com", "companieshouse.gov.uk", "gov.uk", "hmrc.gov.uk",
]

# Regional town breakdown used to fan discovery queries across a locality,
# and to recognise town-keyed branch/listing URL paths (e.g.
# "westcotts.uk/contact-us/holsworthy/") that are not firm homepages.
DISCOVERY_REGION_TOWNS: Dict[str, List[str]] = {
    "north devon": ["Barnstaple", "Bideford", "Ilfracombe", "South Molton",
                     "Torrington", "Braunton", "Lynton", "Holsworthy",
                     "Northam", "Combe Martin"],
    "south devon": ["Totnes", "Dartmouth", "Kingsbridge", "Salcombe",
                     "Ivybridge", "Newton Abbot", "Paignton", "Teignmouth",
                     "Dawlish", "Ashburton"],
    "east devon": ["Honiton", "Sidmouth", "Exmouth", "Seaton",
                    "Axminster", "Ottery St Mary", "Budleigh Salterton",
                    "Crediton", "Tiverton", "Cullompton"],
}

DISCOVERY_ALL_TOWNS = {
    _town.lower()
    for _towns in DISCOVERY_REGION_TOWNS.values()
    for _town in _towns
}


# ============================================================================
# HARNESS RESULT
# ============================================================================


@dataclass
class HarnessResult:
    """
    Result returned by the Harness after executing a Task.
    """

    success: bool

    task: Task

    execution: Optional[TaskExecution] = None

    response: Optional[ModelResponse] = None

    error: Optional[str] = None


# ============================================================================
# AGENT HARNESS
# ============================================================================


class AgentHarness:
    """
    Central orchestration layer for ARNIE.

    Responsibilities:

        - receive Tasks
        - select Agents
        - resolve Model Providers
        - execute model requests
        - emit Events
        - update Task state
        - return structured results

    The Harness does not know about:
        - Discord
        - FastAPI
        - Kokoro
        - SQLite implementation details
        - ChromaDB

    Interfaces and infrastructure sit outside this layer.
    """

    def __init__(
        self,
        agent_registry: Optional[AgentRegistry] = None,
        model_registry: Optional[ModelRegistry] = None,
        event_bus: Optional[EventBus] = None,
        tool_registry: Optional[ToolRegistry] = None,
        memory_store: Optional[MemoryStore] = None,
        voice_service: Optional[VoiceService] = None,
        task_store: Optional[TaskStore] = None,
    ) -> None:
        self.agents = (
            agent_registry
            if agent_registry is not None
            else create_default_agent_registry()
        )

        self.models = (
            model_registry
            if model_registry is not None
            else create_default_model_registry()
        )

        self.events = (
            event_bus
            if event_bus is not None
            else EventBus()
        )

        self.tools = (
            tool_registry
            if tool_registry is not None
            else create_default_registry()
        )

        # Policy is the authorization boundary for Tool execution.
        # The PolicyEngine never executes Tools; it only decides whether the
        # Harness may hand an authorized Tool to the ToolRegistry.
        self.policy = PolicyEngine()

        # Memory is an AgenticOS capability. The Harness receives it as a
        # dependency; it does not own SQLite implementation details.
        self.memory = (
            memory_store
            if memory_store is not None
            else MemoryStore()
        )

        # Tasks are an AgenticOS capability. The Harness receives it as a
        # dependency and drives Task lifecycle transitions around managed
        # Tool execution; it does not own SQLite implementation details.
        self.task_store = (
            task_store
            if task_store is not None
            else TaskStore()
        )

        # Voice is an AgenticOS capability. The Harness exposes the
        # orchestration seam; microphone/STT implementation stays in
        # capabilities.voice.
        self.voice = (
            voice_service
            if voice_service is not None
            else VoiceService()
        )

        # Swarm is an AgenticOS orchestration capability. The Harness owns
        # its lifecycle and injects the canonical model and web capability
        # boundaries. Interface adapters never implement swarm orchestration.
        self.swarm_orchestrator = SwarmManager(
            model_chat=self._swarm_model_chat,
            research_web=deep_research_web,
        )

        # launch_swarm is a canonical Tool. Bind the Harness-owned Swarm
        # capability into the ToolRegistry so normal Policy authorization
        # remains in force before the handler can execute.
        self.tools.bind_handler(
            "launch_swarm",
            self.execute_swarm,
        )

        # run_agency_research is a canonical Tool. Bind the Harness-owned
        # Agency research capability so normal Policy authorization remains
        # in force before the handler can execute.
        self.tools.bind_handler(
            "run_agency_research",
            self.execute_agency_research,
        )

        # run_parallel_agency reuses the same Harness-owned Agency research
        # capability, fanning multiple missions out concurrently.
        self.tools.bind_handler(
            "run_parallel_agency",
            self.execute_run_parallel_agency,
        )

        # generate_image is a canonical Tool. Bind the Harness-owned Media
        # capability so normal Policy authorization remains in force before
        # the handler can execute.
        self.tools.bind_handler(
            "generate_image",
            self.execute_generate_image,
        )

        # add_client, list_clients, and update_client_status are canonical
        # Tools. Bind the Harness-owned Client tracking capability so normal
        # Policy authorization remains in force before the handler can
        # execute.
        self.tools.bind_handler(
            "add_client",
            self.execute_add_client,
        )
        self.tools.bind_handler(
            "list_clients",
            self.execute_list_clients,
        )
        self.tools.bind_handler(
            "update_client_status",
            self.execute_update_client_status,
        )

        # research_prospect, list_prospects, and get_prospect are Phase 24
        # Lead Research Engine tools. Bound here so the Harness owns the
        # web research and data persistence, same pattern as client tools.
        self.tools.bind_handler(
            "research_prospect",
            self.execute_research_prospect,
        )
        self.tools.bind_handler(
            "list_prospects",
            self.execute_list_prospects,
        )
        self.tools.bind_handler(
            "get_prospect",
            self.execute_get_prospect,
        )

        # batch_hunt — research a list of firms in sequence
        self.tools.bind_handler(
            "batch_hunt",
            self.execute_batch_hunt,
        )

        # curate_prospects — post-discovery name quality pass
        self.tools.bind_handler(
            "purge_directory_prospects",
            self.execute_purge_directory_prospects,
        )

        self.tools.bind_handler(
            "curate_prospects",
            self.execute_curate_prospects,
        )

        # draft_outreach is Phase 25 — Outreach Drafting Engine.
        # Bound here so the Harness can call self.chat() for LLM generation.
        self.tools.bind_handler(
            "draft_outreach",
            self.execute_draft_outreach,
        )

        # log_savings_baseline and list_savings_baselines are Phase 26 —
        # Savings Baseline Logger. Bound here so the Harness owns Task
        # lifecycle and data persistence, same pattern as client tools.
        self.tools.bind_handler(
            "log_savings_baseline",
            self.execute_log_savings_baseline,
        )
        self.tools.bind_handler(
            "list_savings_baselines",
            self.execute_list_savings_baselines,
        )

        # log_automation_run and get_monthly_automation_summary are Phase 27
        # — Automation Activity Logger. Bound here so the Harness owns Task
        # lifecycle and data persistence, same pattern as savings baselines.
        self.tools.bind_handler(
            "log_automation_run",
            self.execute_log_automation_run,
        )
        self.tools.bind_handler(
            "get_monthly_automation_summary",
            self.execute_get_monthly_automation_summary,
        )

        # get_client and generate_savings_report are Phase 28 — Monthly
        # Savings Report. get_client reuses the same Client capability as
        # the other client tools; generate_savings_report calls self.chat()
        # so the Harness must own it.
        self.tools.bind_handler(
            "get_client",
            self.execute_get_client,
        )
        self.tools.bind_handler(
            "generate_savings_report",
            self.execute_generate_savings_report,
        )

        # get_client_dashboard is Phase 29 — Client Status Dashboard.
        self.tools.bind_handler(
            "get_client_dashboard",
            self.execute_get_client_dashboard,
        )

        # get_daily_vault_summary needs a model provider, so the Harness owns
        # the provider selection and binds the capability through the Tool
        # Registry. The Vault capability never constructs its own registry.
        self.tools.bind_handler(
            "get_daily_vault_summary",
            self.execute_daily_vault_summary,
        )

        # list_tasks and get_task need the Harness's own Task store instance
        # (which a caller may have injected), so the Harness binds them
        # rather than letting the Tool call a module-level store directly.
        self.tools.bind_handler(
            "list_tasks",
            self.execute_list_tasks,
        )
        self.tools.bind_handler(
            "get_task",
            self.execute_get_task,
        )

    async def _swarm_model_chat(
        self,
        messages: List[Dict[str, str]],
        *,
        model: str = DEFAULT_MODEL,
        capability: str = "reasoning",
    ) -> str:
        """Run a Swarm model request through the canonical ModelProvider."""
        provider = self.select_model_provider()

        request = ModelRequest(
            messages=[
                ModelMessage(
                    role=message["role"],
                    content=message["content"],
                    name=message.get("name"),
                )
                for message in messages
            ],
            capability=capability,
            model=model,
            metadata={"source": "agenticos_swarm"},
        )

        response = await asyncio.to_thread(
            provider.chat,
            request,
        )
        return response.content

    async def execute_daily_vault_summary(self) -> str:
        """Execute the canonical Vault summary with Harness-owned model routing."""
        from capabilities.vault import get_daily_vault_summary

        agent = self.agents.find_by_name("Coordinator")
        if agent is None:
            raise RuntimeError("No Coordinator Agent is registered.")

        provider = self.select_model_provider(agent)
        model = agent.preferred_model() or DEFAULT_MODEL

        summary = await get_daily_vault_summary(
            model_provider=provider,
            model=model,
        )

        # Write summary to vault so the dashboard Vault panel reflects it.
        try:
            from datetime import datetime, timezone
            from capabilities.vault.service import write_obsidian_note
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            note = f"# Daily Vault Summary — {now}\n\n{summary}"
            write_obsidian_note("Daily Summary", note)
        except Exception:
            pass  # best-effort write; never block the return value

        return summary

    async def execute_list_tasks(
        self,
        status: Optional[str] = None,
        workspace: Optional[str] = None,
        limit: int = 10,
    ) -> str:
        """Execute the canonical list_tasks Tool as a human-readable summary."""
        tasks = self.list_tasks(status=status, workspace=workspace, limit=limit)

        if not tasks:
            return "No matching Tasks found."

        lines = [
            f"- [{task['status']}] {task['title']} "
            f"(id={task['id']}, workspace={task['workspace']})"
            for task in tasks
        ]
        return "Tasks:\n" + "\n".join(lines)

    async def execute_get_task(self, task_id: str = "") -> str:
        """Execute the canonical get_task Tool as a human-readable summary."""
        task = self.get_task(task_id)

        if task is None:
            return f"No Task found with id '{task_id}'."

        return (
            f"Task {task['id']}\n"
            f"Title: {task['title']}\n"
            f"Status: {task['status']}\n"
            f"Workspace: {task['workspace']}\n"
            f"Created: {task['created_at']}\n"
            f"Completed: {task.get('completed_at')}\n"
            f"Error: {task.get('error')}"
        )

    async def execute_swarm(
        self,
        mission: str = "Default feature task",
    ) -> str:
        """Execute the canonical SwarmManager through the Tool boundary.

        A Swarm mission is tracked as a first-class Task (workspace="swarm")
        so it survives restart and appears in the dashboard Task panel.
        SwarmManager itself is untouched; the Harness owns the Task
        lifecycle around the single unchanged pipeline call.
        """
        task = Task(
            title=f"Swarm mission: {mission[:60]}",
            description=mission,
            workspace="swarm",
        )
        task.queue()
        self.task_store.save_task(task)

        task.assign("swarm_manager")
        task.start()
        self.task_store.save_task(task)

        try:
            result = await self.swarm_orchestrator.execute_crew_pipeline(
                mission
            )
        except Exception as err:
            task.fail(str(err))
            self.task_store.save_task(task)
            raise

        task.begin_verification()
        self.task_store.save_task(task)

        task.complete(
            TaskResult(
                success=result["is_approved"],
                output=result["default_filename"],
                data={"staged_artifact_id": result["task_id"]},
            )
        )
        self.task_store.save_task(task)

        return (
            "SWARM PIPELINE COMPLETE!\n"
            f"Task ID: {result['task_id']}\n"
            "Artifact staged in memory. "
            f"Default filename: {result['default_filename']}"
        )

    async def execute_agency_research(
        self,
        topic: str = "",
    ) -> str:
        """Run an Agency research mission through the Tool boundary.

        An Agency research mission is tracked as a first-class Task
        (workspace="agency"), the same pattern used for Swarm missions,
        so it survives restart and appears in the dashboard Task panel
        alongside other workspaces. It reuses the existing deep web
        research capability that already powers Swarm, rather than
        introducing a second research implementation.
        """
        task = Task(
            title=f"Agency research: {topic[:60]}",
            description=topic,
            workspace="agency",
        )
        task.queue()
        self.task_store.save_task(task)

        task.assign("iris")
        task.start()
        self.task_store.save_task(task)

        try:
            # ── Build search queries for discovery requests ───────────────
            import re as _sq
            _disc_kws = ("find", "search for", "locate", "hunt for", "get me", "source", "look for")
            _firm_kws = ("accountan", "practice", "firm", "cpa")
            _tl2 = topic.lower()
            _is_disc2 = any(k in _tl2 for k in _disc_kws) and any(k in _tl2 for k in _firm_kws)
            if _is_disc2:
                _loc_m = _sq.search(
                    r"\b(?:in|near|around|from|based\s+in)\s+([\w\s]+?)(?:\s*$|,|\.|\?)",
                    topic, _sq.I,
                )
                _location = _loc_m.group(1).strip() if _loc_m else ""
                _size_m = _sq.search(
                    r"\b(small|medium|mid(?:-sized?)?|large|regional|independent)\b", _tl2
                )
                _size = (_size_m.group(1) + " ") if _size_m else ""
                _count_m = _sq.search(r"\b(\d+)\b", topic)
                _N = min(int(_count_m.group(1)), 10) if _count_m else 5
                if _location:
                    # Build town-specific queries so each slot hits a different firm
                    _loc_key = _location.lower().strip()
                    _towns = DISCOVERY_REGION_TOWNS.get(_loc_key, [])
                    # Exclude the worst directory offenders directly from the
                    # DuckDuckGo query so real firm sites aren't crowded out
                    # of the (small) result window. Capped to keep the query
                    # from becoming so restrictive it returns nothing.
                    _exclude_str = " ".join(
                        f"-site:{d}" for d in DISCOVERY_DIRECTORY_DOMAINS[:12]
                    )
                    if _towns:
                        # One search per town for diversity
                        _slot_queries = [
                            f"accountant {t} {_exclude_str}" for t in _towns
                        ]
                    else:
                        # Generic fallback: vary query types
                        _slot_queries = [
                            f"{_size}accountancy firm {_location} {_exclude_str}",
                            f"chartered accountants {_location} {_exclude_str}",
                            f"tax accountant {_location} {_exclude_str}",
                            f"bookkeeper {_location} {_exclude_str}",
                            f"accounting practice {_location} {_exclude_str}",
                            f"small business accountant {_location} {_exclude_str}",
                            f"payroll accountant {_location} {_exclude_str}",
                            f"management accountant {_location} {_exclude_str}",
                            f"independent accountant {_location} {_exclude_str}",
                            f"local accountant {_location} {_exclude_str}",
                        ]
                    _reports = []
                    for _si in range(_N):
                        _sq2 = _slot_queries[_si % len(_slot_queries)]
                        # crawl_top_n=0: discovery only needs title/URL pairs
                        # from the result list, not scraped page content —
                        # skipping the scrape makes room for more results
                        # per slot instead.
                        _reports.append(
                            await deep_research_web(
                                _sq2, crawl_top_n=0, max_results=8
                            )
                        )
                    report = "\n\n".join(_reports)
                else:
                    report = await deep_research_web(topic)
            else:
                report = await deep_research_web(topic)
        except Exception as err:
            task.fail(str(err))
            self.task_store.save_task(task)
            raise

        task.begin_verification()
        self.task_store.save_task(task)

        task.complete(
            TaskResult(
                success=True,
                output=report,
            )
        )
        self.task_store.save_task(task)

        # ── Auto-batch-hunt on firm discovery requests ──────────────────
        _disc_kw = ("find", "search for", "locate", "hunt for", "get me", "source", "look for")
        _firm_kw = ("accountan", "practice", "firm", "cpa")
        _tl = topic.lower()
        _is_discovery = any(k in _tl for k in _disc_kw) and any(k in _tl for k in _firm_kw)

        batch_summary = ""
        if _is_discovery and report:
            # ── LLM-based firm name extraction via OmniRoute ───────────
            import json as _json2, asyncio as _aio, requests as _req2
            from core.config import OPENAI_COMPAT_HOST as _OAH, OPENAI_COMPAT_API_KEY as _OAK

            _extr_prompt = (
                "You are extracting UK accountancy firm names from a web research report.\n"
                "Return ONLY a JSON array of objects with keys \'name\' and \'url\'.\n"
                "Include only real accountancy firms — not directories, aggregators, or "
                "generic listing sites.\n"
                "Exclude sites like: yell.com, bark.com, checkatrade.com, freeindex.co.uk, "
                "unbiased.co.uk, vouchedfor.co.uk, accountantsup.co.uk, "
                "ukaccountingfirms.co.uk, yelp.com, ratedpeople.com.\n"
                "Skip any title that is keyword-stuffed (multiple profession terms "
                "separated by commas or dashes).\n"
                "Return up to 15 firms. If none found, return [].\n\n"
                f"REPORT:\n{report[:10000]}"
            )

            def _llm_extract():
                try:
                    _resp = _req2.post(
                        f"{_OAH}/chat/completions",
                        headers={"Authorization": f"Bearer {_OAK}"},
                        json={
                            "model": "agent-test",
                            "messages": [{"role": "user", "content": _extr_prompt}],
                            "temperature": 0.1,
                            "max_tokens": 800,
                        },
                        timeout=120,
                    )
                    _resp.raise_for_status()
                    # OmniRoute may stream even when stream=False; handle both
                    try:
                        return _resp.json()["choices"][0]["message"]["content"]
                    except Exception:
                        # SSE fallback
                        _parts = []
                        for _ln in _resp.text.splitlines():
                            if not _ln.startswith("data:"):
                                continue
                            _ds = _ln[5:].strip()
                            if _ds == "[DONE]":
                                break
                            try:
                                import json as _jsse
                                _parts.append(
                                    _jsse.loads(_ds)["choices"][0]["delta"].get("content", "")
                                )
                            except Exception:
                                pass
                        return "".join(_parts)
                except Exception as _ex:
                    return f"__LLM_ERR__{_ex}"

            # ── Per-slot extraction: one firm per search result (fast regex) ──
            import re as _psr, logging as _lg3
            from urllib.parse import urlparse as _psu

            _BLOCK_DOMS = set(DISCOVERY_DIRECTORY_DOMAINS) | set(
                DISCOVERY_SOCIAL_GOV_DOMAINS
            )
            # UK-only: reject the non-UK TLDs most likely to slip through
            # (.com.au etc.), only allow UK/generic ones.
            _ALLOWED_TLD_SUFFIXES = (".co.uk", ".uk", ".com", ".org", ".net")
            _BLOCKED_TLD_SUFFIXES = (
                ".com.au", ".au", ".ca", ".us", ".ie", ".nz", ".co.nz", ".co.za",
            )
            _DIR_PAT = _psr.compile(
                r"^(?:best|top|leading|recommended|local|uk)\s+\d+\s+"
                r"|^(?:\d+\s+)?(?:best|top|leading|recommended)\s+(?:\d+\s+)?"
                r"(?:accountants?|accountanc(?:y|ies)|accounting\s+firms?|firms?)"
                r"(?:\s+in\s+|\s+for\s+|\s+near\s+|$)"
                r"|for\s+20\d\d$",
                _psr.IGNORECASE,
            )
            # "<profession> [for/in/near] <location>" page titles carrying no
            # actual firm brand (e.g. "Accountants For Small Business Combe
            # Martin", "Accountants in Ilfracombe, Devon").
            _NO_FIRM_PAT = _psr.compile(
                r"^(?:local\s+)?(?:chartered\s+)?(?:accountants?|accountancy|accountanc(?:y|ies)|"
                r"bookkeepers?|bookkeeping|tax\s+(?:advisors?|services?|specialists?|"
                r"accountants?))(?:\s+(?:for|in|near|\w+)\b|\s+firm\b|\s+practice\b|$)",
                _psr.IGNORECASE,
            )
            # Boilerplate page-title prefixes that hide the real firm name.
            _TITLE_PREFIX_PAT = _psr.compile(
                r"^(?:welcome\s+to|find|best|top)\s+", _psr.IGNORECASE,
            )
            _SEP_PAT = _psr.compile(r"\s*(?:\s[-\u2013\u2014]\s|\|).*$")
            _GENERIC_TITLES = _psr.compile(
                r"^(?:chartered\s+)?(?:accountanc(?:y|ies)|accountants?|"
                r"accounting\s+firm|bookkeeping|tax\s+services?)\s*$",
                _psr.IGNORECASE,
            )
            # Path segments marking a branch/contact/listing page rather than
            # a firm's real homepage (e.g. ".../accountants/ilfracombe/" or
            # "westcotts.uk/contact-us/holsworthy/").
            _BRANCH_PATH_MARKERS = {"accountants", "contact-us", "contact", "offices", "locations"}
            # Single-word junk page titles (homepage fallbacks, nav items etc.)
            _JUNK_WORDS = {
                "home", "contact", "about", "welcome", "services", "news",
                "blog", "sitemap", "menu", "login", "register", "search",
                "results", "directory", "index",
            }
            # "[Location/word] [profession keyword]" e.g. "Bideford Accountant"
            # catches profession-suffix patterns that _NO_FIRM_PAT misses
            _LOC_PROF_PAT = _psr.compile(
                r"^[\w][\w\s]{1,30}\s+(?:chartered\s+)?(?:accountants?|accountancy|"
                r"accountanc(?:y|ies)|bookkeepers?|bookkeeping|"
                r"tax\s+(?:advisors?|services?|specialists?|accountants?))s?$",
                _psr.IGNORECASE,
            )

            _CANDIDATE_PAT = _psr.compile(
                r"^#{0,3}\s*\d+\.\s+(.+?)\n\*{0,2}URL:\*{0,2}\s*(https?://\S+)",
                _psr.MULTILINE,
            )

            def _iter_candidates(_report_text):
                for _m in _CANDIDATE_PAT.finditer(_report_text):
                    yield _m.group(1).strip(), _m.group(2).strip()

            def _domain_brand_name(_dom):
                _base = _dom.split(".")[0]
                return _base.replace("-", " ").replace("_", " ").strip().title()

            _firm_entries: list[str] = []
            _seen_names: set[str] = set()
            _seen_domains: set[str] = set()  # domain-level dedup
            # Seed from existing prospects to avoid re-researching
            try:
                from capabilities.prospects.service import list_prospects as _lp
                for _ep in _lp():
                    _seen_names.add((_ep.firm_name or "").lower().strip())
            except Exception:
                pass

            def _try_extract(_raw_title, _url):
                # Skip Bing ad redirects
                if "bing.com/aclick" in _url or "bing.com/ck/a" in _url:
                    return None
                _parsed = _psu(_url)
                _dom = _parsed.netloc.lower()
                if _dom.startswith("www."):
                    _dom = _dom[4:]
                if not _dom or _dom in _BLOCK_DOMS or any(_dom.endswith("." + _bd) for _bd in _BLOCK_DOMS):
                    return None
                if any(_dom.endswith(_sfx) for _sfx in _BLOCKED_TLD_SUFFIXES):
                    return None
                if not any(_dom.endswith(_sfx) for _sfx in _ALLOWED_TLD_SUFFIXES):
                    return None

                _path_segs = [s for s in _parsed.path.lower().split("/") if s]
                _is_branch_path = False
                if _path_segs:
                    _last_seg = _path_segs[-1].replace("-", " ")
                    _is_branch_path = (
                        _last_seg in DISCOVERY_ALL_TOWNS
                        or (len(_path_segs) >= 2 and _path_segs[-2] in _BRANCH_PATH_MARKERS)
                    )

                if _is_branch_path:
                    # Title on a branch/listing page is unreliable \u2014 use the
                    # domain's own brand name instead (e.g. "Westcotts" from
                    # westcotts.uk/contact-us/holsworthy/).
                    _name = _domain_brand_name(_dom)
                    if not _name or len(_name) < 3 or _name.lower() in DISCOVERY_ALL_TOWNS:
                        return None
                else:
                    if _DIR_PAT.search(_raw_title):
                        return None
                    _title = _TITLE_PREFIX_PAT.sub("", _raw_title).strip()
                    _name = _SEP_PAT.sub("", _title).strip()
                    if not _name or len(_name) < 4:
                        return None
                    # Skip generic profession-keyword-only titles
                    if _GENERIC_TITLES.match(_name):
                        return None
                    # Skip "<profession> for/in/near <location>" non-firm titles
                    if _NO_FIRM_PAT.search(_name):
                        return None
                    # Skip "[Location] [profession]" reverse patterns
                    if _LOC_PROF_PAT.match(_name):
                        return None
                    # Skip single junk words (e.g. "Home", "Contact")
                    if _name.lower().strip() in _JUNK_WORDS:
                        return None
                    if _name.lower() in DISCOVERY_ALL_TOWNS:
                        return None

                _nk = _name.lower()
                if _nk in _seen_names or _dom in _seen_domains:
                    return None  # try next result in this slot
                _seen_names.add(_nk)
                _seen_domains.add(_dom)
                return f"{_name} | {_url}"

            _slot_reports = [s.strip() for s in report.split("# SEARCH RESULTS FOR:") if s.strip()]
            if not _slot_reports:
                _slot_reports = [report]

            for _sr in _slot_reports:
                # Walk all (title, url) pairs in this slot; take first valid one
                for _raw_title, _url in _iter_candidates(_sr):
                    _entry = _try_extract(_raw_title, _url)
                    if _entry:
                        _firm_entries.append(_entry)
                        break  # one firm per slot

            # \u2500\u2500 Fallback: broaden the query for slots that produced nothing \u2500\u2500
            # (small towns like Lynton/Combe Martin may have no indexed firm
            # site) instead of wasting the slot entirely.
            _fb_location = locals().get("_location", "")
            _fb_exclude_str = locals().get("_exclude_str", "")
            _fb_target = locals().get("_N", 0)
            if _fb_target and len(_firm_entries) < _fb_target:
                _region_words = _fb_location.split() if _fb_location else []
                _broad_region = (
                    _region_words[-1] if len(_region_words) > 1 else (_fb_location or "Devon")
                )
                _fallback_queries = []
                if _fb_location:
                    _fallback_queries.append(f"accountant {_fb_location} {_fb_exclude_str}".strip())
                _fallback_queries.append(f"chartered accountant {_broad_region} {_fb_exclude_str}".strip())

                _fb_idx = 0
                _fb_attempts = 0
                while len(_firm_entries) < _fb_target and _fb_attempts < 4:
                    _fbq = _fallback_queries[_fb_idx % len(_fallback_queries)]
                    _fb_idx += 1
                    _fb_attempts += 1
                    try:
                        _fb_report = await deep_research_web(_fbq, crawl_top_n=0, max_results=8)
                    except Exception:
                        continue
                    for _raw_title, _url in _iter_candidates(_fb_report):
                        if len(_firm_entries) >= _fb_target:
                            break
                        _entry = _try_extract(_raw_title, _url)
                        if _entry:
                            _firm_entries.append(_entry)

            firm_names = _firm_entries
            if firm_names:
                try:
                    batch_summary = await self.execute_batch_hunt(firms="\n".join(firm_names))
                except Exception as _be:
                    batch_summary = f"[Batch hunt failed: {_be}]"

        # Build a short outcome line rather than dumping the full report to chat
        if batch_summary and not batch_summary.startswith("[Batch hunt failed"):
            import re as _rs
            _hunted = len(_rs.findall(r"Prospect researched:", batch_summary))
            _outcome = f"Iris queued {len(firm_names)} firm{'s' if len(firm_names)!=1 else ''} — {_hunted} researched. View results at /prospects"
        elif batch_summary.startswith("[Batch hunt failed"):
            _outcome = batch_summary
        else:
            _outcome = "Research complete — no firm names extracted for batch hunt."

        return (
            f"AGENCY RESEARCH COMPLETE\n"
            f"Task ID: {task.id}\n\n"
            f"{_outcome}"
        )

    async def execute_run_parallel_agency(
        self,
        topics: List[str] | None = None,
        context: str = "",
    ) -> str:
        """Fan multiple Agency research missions out concurrently.

        Each topic reuses execute_agency_research, so every sub-mission
        gets its own first-class Task (workspace="agency") exactly as a
        single run_agency_research call would. Concurrency is capped by
        PARALLEL_AGENCY_MAX_WORKERS; one sub-mission's failure is caught
        individually so it cannot cancel the others.
        """
        from .config import PARALLEL_AGENCY_MAX_WORKERS

        topics = (topics or [])[:PARALLEL_AGENCY_MAX_WORKERS]

        if not topics:
            return "No topics provided."

        async def _run_one(topic: str) -> str:
            mission = f"{topic}\n\nContext: {context}" if context else topic
            try:
                return await self.execute_agency_research(topic=mission)
            except Exception as err:
                return f"[{topic}] failed: {err}"

        results = await asyncio.gather(*[_run_one(topic) for topic in topics])

        sections = [
            f"## {topic}\n{result}"
            for topic, result in zip(topics, results)
        ]
        return "\n\n---\n\n".join(sections)

    async def execute_generate_image(
        self,
        prompt: str = "",
        negative_prompt: str = "",
        steps: int = 0,
    ) -> str:
        """Generate an image through the Media capability Tool boundary.

        Image generation is tracked as a first-class Task
        (workspace="media"), following the same pattern as Swarm and
        Agency.  The actual HTTP call is delegated to ImageGenService
        so core/ never touches the image generation API directly.
        """
        from capabilities.media.service import ImageGenService
        from core.config import (
            IMAGE_GEN_ENABLED,
            IMAGE_GEN_HOST,
            IMAGE_GEN_OUTPUT_DIR,
            IMAGE_GEN_DEFAULT_STEPS,
        )

        effective_steps = steps if steps > 0 else IMAGE_GEN_DEFAULT_STEPS

        task = Task(
            title=f"Generate image: {prompt[:55]}",
            description=prompt,
            workspace="media",
        )
        task.queue()
        self.task_store.save_task(task)

        task.assign("media")
        task.start()
        self.task_store.save_task(task)

        try:
            service = ImageGenService(
                host=IMAGE_GEN_HOST,
                output_dir=IMAGE_GEN_OUTPUT_DIR,
                enabled=IMAGE_GEN_ENABLED,
            )
            result = service.generate(
                prompt,
                negative_prompt=negative_prompt,
                steps=effective_steps,
            )
        except Exception as err:
            task.fail(str(err))
            self.task_store.save_task(task)
            raise

        task.begin_verification()
        self.task_store.save_task(task)

        task.complete(
            TaskResult(
                success=True,
                output=result.path,
            )
        )
        self.task_store.save_task(task)

        return (
            "IMAGE GENERATION COMPLETE\n"
            f"Task ID: {task.id}\n"
            f"{result}"
        )

    async def execute_add_client(
        self,
        name: str = "",
        service: str = "",
        notes: str = "",
    ) -> str:
        """Add a new agency client through the Client capability Tool boundary.

        Client creation is tracked as a first-class Task (workspace="client"),
        following the same pattern as Swarm, Agency, and Media. The actual
        JSON persistence is delegated to capabilities.clients.service so
        core/ never touches the client store file directly.
        """
        from capabilities.clients.service import add_client

        task = Task(
            title=f"Add client: {name[:55]}",
            description=f"service={service}",
            workspace="client",
        )
        task.queue()
        self.task_store.save_task(task)

        task.assign("coordinator")
        task.start()
        self.task_store.save_task(task)

        try:
            client = add_client(name=name, service=service, notes=notes)
        except Exception as err:
            task.fail(str(err))
            self.task_store.save_task(task)
            raise

        task.begin_verification()
        self.task_store.save_task(task)

        task.complete(
            TaskResult(
                success=True,
                output=client.id,
            )
        )
        self.task_store.save_task(task)

        return (
            f"Client added: {client.name} "
            f"(ID: {client.id}, status: {client.status})"
        )

    async def execute_list_clients(
        self,
        status: Optional[str] = None,
    ) -> str:
        """Execute the canonical list_clients Tool as a human-readable summary."""
        from capabilities.clients.service import list_clients

        clients = list_clients(status=status)

        if not clients:
            return "No clients found."

        lines = [
            f"- {client.name} [{client.status}] — "
            f"{client.service} (ID: {client.id})"
            for client in clients
        ]
        return "\n".join(lines)

    async def execute_update_client_status(
        self,
        client_id: str = "",
        status: str = "",
        notes: str = "",
    ) -> str:
        """Update a client's status through the Client capability Tool boundary.

        The status change is tracked as a first-class Task (workspace="client"),
        following the same pattern as Swarm, Agency, and Media.
        """
        from capabilities.clients.service import update_client_status

        task = Task(
            title=f"Update client {client_id} -> {status}",
            description=notes,
            workspace="client",
        )
        task.queue()
        self.task_store.save_task(task)

        task.assign("coordinator")
        task.start()
        self.task_store.save_task(task)

        try:
            client = update_client_status(
                client_id=client_id,
                status=status,
                notes=notes,
            )
        except Exception as err:
            task.fail(str(err))
            self.task_store.save_task(task)
            raise

        if client is None:
            task.fail(f"Client '{client_id}' not found.")
            self.task_store.save_task(task)
            return f"Client {client_id} not found."

        task.begin_verification()
        self.task_store.save_task(task)

        task.complete(
            TaskResult(
                success=True,
                output=client.status,
            )
        )
        self.task_store.save_task(task)

        return f"Updated {client.name} → {status}"

    async def execute_research_prospect(
        self,
        firm_name: str = "",
        website: str = "",
    ) -> str:
        """Research a UK accountancy practice and build a structured lead profile.

        Phase 24+: Lead Research Engine (structured intelligence).
        Runs three targeted web searches, then synthesises a ProspectIntelligence
        record with graded PainSignals, scoring, verdict and outreach intel.
        """
        from capabilities.web.research import deep_research_web
        from capabilities.web.search import web_search
        from capabilities.prospects.service import (
            add_prospect, get_prospect_by_name, update_prospect_intel,
            PainSignal, OutreachIntel, MoneyValue
        )

        if not firm_name:
            return "Error: firm_name is required."

        # ── Reject directory/aggregator sites before spending tokens ──────
        import re as _re2
        _SKIP_DOMAINS = {
            "accountantsup.co.uk", "ukaccountingfirms.co.uk", "checkatrade.com",
            "yell.com", "bark.com", "freeindex.co.uk", "thomsonlocal.com",
            "ratedpeople.com", "trustatrader.com", "yelp.com",
        }
        _DIR_NAME_RE = _re2.compile(
            r"^(?:best|top|leading|recommended)\s+\d+\s+"
            r"|^(?:\d+\s+)?(?:best|top|leading|recommended)\s+(?:\d+\s+)?"
            r"(?:accountants?|accountanc(?:y|ies)|accounting\s+firms?|firms?|practices?)"
            r"(?:\s+in\s+|\s+for\s+|\s+near\s+|$)|for\s+20\d\d$",
            _re2.IGNORECASE,
        )
        _skip = _DIR_NAME_RE.search(firm_name)
        if not _skip and website:
            from urllib.parse import urlparse
            _dom = urlparse(website).netloc.lstrip("www.")
            _skip = _dom in _SKIP_DOMAINS
        if _skip:
            return f"[Skipped] '{firm_name}' identified as a directory/aggregator page — not a prospect."

        task = Task(
            title=f"Research prospect: {firm_name[:50]}",
            description=f"website={website or 'not provided'}",
            workspace="prospects",
        )
        task.queue()
        self.task_store.save_task(task)
        task.assign("iris")
        task.start()
        self.task_store.save_task(task)

        # Generic homepage titles ("Home", "404", ...) carry no business
        # identity — when the cleaned title lands here, fall back to a name
        # derived from the domain instead of using the title verbatim.
        _GENERIC_TITLES = {
            "home", "welcome", "index", "untitled", "coming soon",
            "under construction", "page not found", "404", "403", "error",
        }

        def _derive_name_from_domain(domain: str) -> str:
            import re as _dom_re
            d = domain.strip()
            if d.lower().startswith("www."):
                d = d[4:]
            leftmost = d.split(".")[0]
            parts = [p for p in _dom_re.split(r"[-_]+", leftmost) if p]
            if not parts:
                return leftmost.title()
            return " ".join(p.title() for p in parts)

        try:
            # ── Name resolution: if firm_name looks like a domain, resolve it ──
            import re as _nm_re
            if _nm_re.match(r'^[\w.-]+\.(co\.uk|com|org\.uk|org|net)$', firm_name, _nm_re.I):
                # firm_name IS a domain — resolve real business name from the site
                _original_domain = firm_name
                _resolve = await deep_research_web(f"site:{_original_domain}", crawl_top_n=1)
                _title_m = _nm_re.search(r'###\s*\d+\.\s+([^\n]{4,80})', _resolve)
                if _title_m:
                    _resolved = _title_m.group(1).strip()
                    # Strip SEO suffixes
                    _resolved = _nm_re.sub(r'\s*(?:\s[-–]\s|\|).*$', '', _resolved).strip()
                    _is_generic = (
                        _resolved.lower() in _GENERIC_TITLES
                        or _nm_re.match(r'(?:chartered\s+)?accountants?\s+', _resolved, _nm_re.I)
                        or _nm_re.match(r'\w[\w\s]{0,25}\s+accountant$', _resolved, _nm_re.I)
                    )
                    if _resolved and _is_generic:
                        firm_name = _derive_name_from_domain(_original_domain)
                    elif _resolved and not _nm_re.search(
                        r'accountants?\s+in\b|\bfind\b|\bbest\b', _resolved, _nm_re.I
                    ):
                        firm_name = _resolved
                if not website:
                    website = f"https://{_original_domain}"

            # ── Direct site scrape: first-party evidence, most reliable ────
            # DDG snippets frequently echo query keywords back from unrelated
            # ad/directory pages (e.g. a job-board ad matches "hiring" for
            # every query that asks about hiring), which was producing an
            # identical false-positive signal set for every prospect. Actual
            # page content from the firm's own site is trustworthy; search
            # results are only trusted once filtered for relevance below.
            site_content = ""
            if website:
                from capabilities.web.research import scrape_web_page_stealth
                _scraped = await scrape_web_page_stealth(website)
                if not _scraped.startswith("Web scrape failure"):
                    site_content = _scraped
                    # ── Extract real brand name from SITE_TITLE ──────────────
                    import re as _nt_re
                    _title_m = _nt_re.match(r"SITE_TITLE:\s*(.+)", site_content)
                    if _title_m:
                        _raw_title = _title_m.group(1).strip()
                        # Strip SEP suffixes (| Accountants in Devon, - Home etc.)
                        _clean_title = _nt_re.sub(
                            r"\s*(?:\s[-–—]\s|\|).*$", "", _raw_title
                        ).strip()
                        # Only override firm_name if the site title looks like a
                        # real brand (not itself a generic keyword title)
                        _is_kw = _nt_re.match(
                            r"^(?:home|contact|about|welcome|services|news|menu|"
                            r"(?:local\s+)?(?:chartered\s+)?accountants?|accountancy|"
                            r"bookkeeping|tax\s+(?:services?|advisors?))\s*$",
                            _clean_title, _nt_re.I
                        )
                        _looks_brand = (
                            _clean_title
                            and not _is_kw
                            and len(_clean_title) >= 3
                            and len(_clean_title) <= 80
                        )
                        # Override firm_name when current name is generic/junk
                        _cur_is_junk = _nt_re.match(
                            r"^(?:home|contact|about|welcome|services|news|menu)$",
                            firm_name, _nt_re.I
                        ) or _nt_re.match(
                            r"^(?:[\w\s]+\s+)?(?:chartered\s+)?(?:accountants?|accountancy|"
                            r"bookkeepers?|bookkeeping|tax\s+(?:advisors?|services?|specialists?))"
                            r"(?:\s+[\w\s]*)?$",
                            firm_name, _nt_re.I
                        )
                        if _looks_brand and _cur_is_junk:
                            firm_name = _clean_title

            # Search 1: General firm info + page extract
            general_query = f'"{firm_name}" accountant UK'
            if website:
                general_query += f" {website}"
            general_research = await deep_research_web(general_query, crawl_top_n=1)

            # Search 2: Software stack signals
            stack_results = web_search(
                f'"{firm_name}" accountant Xero QuickBooks Sage FreeAgent'
            )

            # Search 3: Pain signals — reviews and job listings
            pain_results = web_search(
                f'"{firm_name}" accountant UK reviews hiring jobs vacancy'
            )

            # Search 4: Staff size signals (moved earlier — feeds value_score)
            size_results = web_search(
                f'"{firm_name}" accountant UK partners staff employees team'
            )

            # ── Relevance filtering: discard generic ad/directory noise ────
            # A search-result block is only trusted as evidence if it
            # actually names the firm or its own domain — this is what
            # stops every prospect inheriting the same generic "hiring" /
            # "reviews" ad copy that happens to contain the query's words.
            from urllib.parse import urlparse as _urlparse
            _domain = _urlparse(website).netloc.lower() if website else ""
            if _domain.startswith("www."):
                _domain = _domain[4:]
            _STOP_TOKENS = {
                "accountants", "accountant", "accountancy", "accounting",
                "chartered", "the", "and", "of", "uk", "ltd", "llp", "co",
            }
            _name_tokens = [
                t for t in _re2.findall(r"[a-z]+", firm_name.lower())
                if len(t) > 2 and t not in _STOP_TOKENS
            ] or [t for t in _re2.findall(r"[a-z]+", firm_name.lower()) if len(t) > 2]

            def _is_relevant_block(block: str) -> bool:
                b = block.lower()
                if _domain and _domain in b:
                    return True
                return any(t in b for t in _name_tokens)

            def _filter_relevant(text: str) -> str:
                blocks = _re2.split(r"\n\n+", text)
                return "\n\n".join(b for b in blocks if _is_relevant_block(b))

            general_relevant = _filter_relevant(general_research)
            stack_relevant   = _filter_relevant(stack_results)
            pain_relevant    = _filter_relevant(pain_results)
            size_relevant    = _filter_relevant(size_results)

            combined      = (site_content + " " + general_relevant + " " + stack_relevant).lower()
            pain_lower    = (site_content + " " + pain_relevant).lower()
            general_lower = (site_content + " " + general_relevant).lower()
            size_lower    = (size_relevant + " " + general_lower)

            # ── Software stack detection ──────────────────────────────────
            software_stack = "unknown"
            for sw in ["xero", "quickbooks", "sage", "freeagent", "kashflow", "iris"]:
                if sw in combined:
                    software_stack = sw.title()
                    break

            # ── Structured pain signal extraction ─────────────────────────
            # Every signal below is grounded in filtered/first-party text —
            # generic query-keyword echoes from irrelevant pages never reach
            # here, so signals (and therefore scores) now vary per firm.
            signals = []

            if any(w in pain_lower for w in ["hiring", "vacancy", "job opening", "recruit", "join our team"]):
                signals.append(PainSignal(
                    description="Hiring activity detected — likely capacity pressure",
                    evidence=(pain_relevant or site_content)[:200],
                    strength="OBSERVED",
                ))

            if any(w in pain_lower for w in ["manual", "spreadsheet", "excel"]):
                signals.append(PainSignal(
                    description="Manual / spreadsheet process signals in public content",
                    evidence=(pain_relevant or site_content)[:200],
                    strength="INDICATED",
                ))

            if any(w in general_lower for w in ["growing", "expansion", "new office", "new partner"]):
                signals.append(PainSignal(
                    description="Growth indicators — scaling pains probable",
                    evidence=(general_relevant or site_content)[:200],
                    strength="INDICATED",
                ))

            # Confirmed software is a business-snapshot fact (captured in
            # software_stack / the primary thesis below), not a pain signal —
            # nearly every UK accountancy site mentions Xero somewhere, so
            # treating "has Xero" as an OBSERVED pain point would just
            # converge every prospect onto the same score again. Only the
            # *absence* of a confirmed stack is a real signal.
            if software_stack == "unknown":
                if site_content or general_relevant or stack_relevant:
                    signals.append(PainSignal(
                        description="No dominant accounting software mentioned in available content — possible legacy or fragmented stack",
                        evidence=(site_content or general_relevant or stack_relevant)[:200],
                        strength="INDICATED",
                    ))
                else:
                    # Only fall back to the generic "no info" hypothesis when
                    # we genuinely found nothing usable about this firm.
                    signals.append(PainSignal(
                        description="No dominant accounting software identified — potential legacy or fragmented stack",
                        evidence="No firm-specific content found in search results",
                        strength="HYPOTHESISED",
                    ))

            # ── Staff size estimate (feeds both urgency and value scoring) ──
            staff_estimate = None
            if any(w in size_lower for w in ["sole trader", "sole practitioner", "one-man", "1 partner"]):
                staff_estimate = ("tiny", 1, 3)
            elif any(w in size_lower for w in ["boutique", "small practice", "2 partner", "3 partner"]):
                staff_estimate = ("small", 3, 8)
            elif any(w in size_lower for w in ["10 staff", "12 staff", "15 staff", "20 staff", "regional", "growing team"]):
                staff_estimate = ("medium", 10, 25)
            elif any(w in size_lower for w in ["50 staff", "100 staff", "national", "multiple offices"]):
                staff_estimate = ("large", 40, 100)
            hiring_signal = any(s.strength == "OBSERVED" and "hiring" in s.description.lower() for s in signals)
            if hiring_signal and staff_estimate is None:
                staff_estimate = ("small", 4, 12)

            # ── Companies House: real filing/incorporation facts ───────────
            # Replaces inferred signals with hard facts where a confident
            # match exists; falls back to the website-based heuristics above
            # when it doesn't (no API key configured, no confident match, or
            # the API was unavailable — lookup_company() never raises).
            ch_facts = None
            try:
                from capabilities.companies_house.service import lookup_company
                ch_facts = await asyncio.to_thread(lookup_company, firm_name)
            except Exception:
                ch_facts = None
            companies_house_number = ch_facts.get("company_number", "") if ch_facts else ""
            if ch_facts and ch_facts.get("late_filing_detected"):
                signals.append(PainSignal(
                    description="Filed accounts late — operational stress indicator",
                    evidence=f"CH filing date: {ch_facts.get('late_filing_date')}",
                    strength="OBSERVED",
                ))

            # ── Scoring heuristics (0–5) — derived from grounded evidence ───
            observed_count   = sum(1 for s in signals if s.strength == "OBSERVED")
            indicated_count  = sum(1 for s in signals if s.strength == "INDICATED")
            pain_score          = min(5, observed_count * 2 + indicated_count)
            urgency_score       = 2 if observed_count else (1 if indicated_count else 0)
            if ch_facts and ch_facts.get("late_filing_detected"):
                urgency_score   = min(5, urgency_score + 2)

            # value_score: prefer a real CH employee count over the website
            # inference when we have one; otherwise keep existing behaviour.
            ch_employee_count = ch_facts.get("employee_count") if ch_facts else None
            if isinstance(ch_employee_count, (int, float)) and ch_employee_count > 0:
                n = int(ch_employee_count)
                if n <= 4:
                    value_score = 2
                elif n <= 9:
                    value_score = 3
                elif n <= 19:
                    value_score = 4
                else:
                    value_score = 5
            else:
                _size_to_value  = {"tiny": 1, "small": 2, "medium": 3, "large": 5}
                value_score     = _size_to_value.get(staff_estimate[0], 1) if staff_estimate else 1
            repeatability_score = 3   # accountancy = recurring by nature (business-model constant)

            # ── Verdict ───────────────────────────────────────────────────
            # High value/urgency alone doesn't earn a Hunt/Watch verdict — a
            # firm with no real pain signal is not worth chasing regardless
            # of total score, so each tier floors on pain_score too.
            total = pain_score + urgency_score + value_score + repeatability_score
            if total >= 10 and pain_score >= 2:
                verdict = "A"
            elif total >= 6 and pain_score >= 1:
                verdict = "B"
            else:
                verdict = "C"

            # Evidence-driven confidence — varies per prospect
            evidence_confidence = 30 if signals else 15
            if any(s.strength == "OBSERVED" for s in signals):
                evidence_confidence = min(60, evidence_confidence + 20)
            if len(signals) >= 3:
                evidence_confidence = min(70, evidence_confidence + 10)
            _tier_bonus = {"A": 20, "B": 10, "C": 0}
            confidence = min(85, evidence_confidence + _tier_bonus[verdict])

            # ── Primary thesis ────────────────────────────────────────────
            signal_summary = "; ".join(s.description for s in signals) if signals else "No strong signals yet"
            stack_str = f" using {software_stack}" if software_stack != "unknown" else " with unconfirmed software stack"
            verdict_label = "Hunt" if verdict == "A" else "Watch" if verdict == "B" else "Pass"
            primary_thesis = (
                f"{firm_name} is a UK accountancy practice{stack_str}. "
                f"Commercial signals: {signal_summary}. "
                f"Verdict {verdict} ({verdict_label}) based on initial research — confidence {confidence}%."
            )

            # ── Outreach intel ────────────────────────────────────────────
            why_now = ""
            if any(s.strength == "OBSERVED" and "hiring" in s.description.lower() for s in signals):
                why_now = "Actively hiring — signals capacity strain and openness to outsourced support"
            elif any(s.strength == "INDICATED" for s in signals):
                why_now = "Multiple indirect signals of operational friction"

            has_manual = any("manual" in s.description.lower() for s in signals)
            outreach_angle = (
                f"We help accountancy practices like {firm_name} "
                + ("move off manual processes " if has_manual else "streamline client delivery ")
                + "without hiring headcount."
            )

            oi = OutreachIntel(
                why_now=why_now,
                outreach_angle=outreach_angle,
                objections=["We're not looking to change right now", "We already have a system"],
            )

            # ── Staff size → MoneyValue (package-based pricing) ──
            # Packages: The Chaser / The Reconciler / The Filer — each £750/mo
            BANDS = {
                #           pkgs_lo  pkgs_hi  conf  bslo bshi
                "tiny":   (1,       1,       30,   1,   4),
                "small":  (1,       2,       40,   5,   9),
                "medium": (2,       2,       45,   10,  19),
                "large":  (2,       3,       40,   20,  49),
            }
            PKG_MONTHLY = 750
            if staff_estimate:
                band_name, slo, shi = staff_estimate
                pkgs_lo, pkgs_hi, conf, bslo, bshi = BANDS[band_name]
                pkgs_mid = (pkgs_lo + pkgs_hi) / 2
                lo  = int(pkgs_lo  * PKG_MONTHLY * 12)
                hi  = int(pkgs_hi  * PKG_MONTHLY * 12)
                mid = int(pkgs_mid * PKG_MONTHLY * 12)
                fv = MoneyValue(
                    status="known",
                    amount_gbp=mid,
                    range_low=lo,
                    range_high=hi,
                    basis=f"~{bslo}\u2013{bshi} staff → est. {pkgs_lo}\u2013{pkgs_hi} package(s) @ £{PKG_MONTHLY}/mo",
                    confidence=conf,
                )
            else:
                fv = MoneyValue(
                    status="unknown",
                    basis="Insufficient size signals in public data",
                    confidence=0,
                )

            # ── Niche detection ────────────────────────────────────────
            niche_results = web_search(
                f'"{firm_name}" accountant specialist clients sector industry' 
            )
            niche_lower = _filter_relevant(niche_results).lower()
            NICHE_MAP = [
                ("construction", ["construction", "builders", "subcontractors", "cis", "contractors"]),
                ("hospitality", ["hospitality", "restaurants", "hotels", "pubs", "catering"]),
                ("property & landlords", ["landlords", "property", "letting agents", "real estate"]),
                ("legal & professional", ["solicitors", "legal", "law firms", "barristers"]),
                ("medical & dental", ["medical", "dental", "gp", "healthcare", "nhs", "clinics"]),
                ("creative & media", ["creative", "media", "agencies", "design", "production"]),
                ("freelancers & contractors", ["freelancers", "contractors", "ir35", "limited companies"]),
                ("ecommerce & retail", ["ecommerce", "retail", "amazon", "shopify", "online"]),
                ("charities & not-for-profit", ["charity", "charities", "not-for-profit", "nfp"]),
            ]
            niche = ""
            for niche_name, keywords in NICHE_MAP:
                if any(kw in niche_lower or kw in general_lower for kw in keywords):
                    niche = niche_name
                    break

            # ── Unknowns & contradictions ──────────────────────────────
            unknowns = []
            contradictions = []
            if software_stack == "unknown":
                unknowns.append("Software stack — no Xero/QBO/Sage/Iris mention found")
            if not staff_estimate:
                unknowns.append("Staff size — no headcount signals in public data")
            if not niche:
                unknowns.append("Client niche — sector specialisation not identifiable from search")
            if not signals:
                unknowns.append("Pain signals — no strong operational friction signals found")
            # Contradictions: hiring but also described as boutique/small
            hiring_obs = any("hiring" in s.description.lower() and s.strength == "OBSERVED" for s in signals)
            boutique_sig = any(w in (niche_lower + general_lower) for w in ["boutique", "sole practitioner", "one-man"])
            if hiring_obs and boutique_sig:
                contradictions.append("Hiring signals contradict boutique/sole-practitioner positioning — actual size unclear")

            # ── Raw notes ─────────────────────────────────────────────────
            ch_note = (
                f"#{companies_house_number}, incorporated {ch_facts.get('date_of_creation', 'unknown')}, "
                f"accounts next due {ch_facts.get('accounts_next_due', 'unknown')}"
                if ch_facts else "no match"
            )
            raw_notes = (
                f"Site: {site_content[:300] if site_content else '(scrape unavailable)'}\n"
                f"General: {general_research[:300]}\n"
                f"Stack: {stack_results[:200]}\n"
                f"Pain: {pain_results[:200]}\n"
                f"Companies House: {ch_note}"
            )

            # ── Upsert: patch existing record if firm already known ────
            existing = get_prospect_by_name(firm_name)
            if existing is not None:
                prospect = update_prospect_intel(
                    existing.id,
                    firm_name=firm_name,
                    verdict=verdict,
                    confidence=confidence,
                    evidence_confidence=evidence_confidence,
                    primary_thesis=primary_thesis,
                    pain_signals=signals,
                    pain_score=pain_score,
                    value_score=value_score,
                    urgency_score=urgency_score,
                    repeatability_score=repeatability_score,
                    financial_value=fv,
                    outreach_intel=oi,
                    niche=niche,
                    software_stack=software_stack,
                    companies_house_number=companies_house_number,
                    unknowns=unknowns,
                    contradictions=contradictions,
                    notes=raw_notes,
                )
            else:
                prospect = add_prospect(
                    firm_name=firm_name,
                    website=website,
                    software_stack=software_stack,
                    companies_house_number=companies_house_number,
                    niche=niche,
                    verdict=verdict,
                    confidence=confidence,
                    evidence_confidence=evidence_confidence,
                    primary_thesis=primary_thesis,
                    pain_signals=signals,
                    pain_score=pain_score,
                    value_score=value_score,
                    urgency_score=urgency_score,
                    repeatability_score=repeatability_score,
                    financial_value=fv,
                    outreach_intel=oi,
                    unknowns=unknowns,
                    contradictions=contradictions,
                    notes=raw_notes,
                )

        except Exception as err:
            task.fail(str(err))
            self.task_store.save_task(task)
            raise

        task.begin_verification()
        self.task_store.save_task(task)
        task.complete(TaskResult(success=True, output=prospect.id))
        self.task_store.save_task(task)

        # Auto-log time saved (45 min manual research equivalent)
        try:
            from core.db import log_activity
            log_activity("prospect_research", prospect.firm_name, minutes_saved=45)
        except Exception:
            pass

        # Auto-queue Maya outreach task for grade-A prospects
        if verdict == "A":
            try:
                outreach_task = Task(
                    title=f"Draft outreach: {prospect.firm_name[:45]}",
                    description=(
                        f"Grade A prospect — ready for personalised outreach.\n"
                        f"Call draft_outreach with prospect_id={prospect.id}"
                    ),
                    workspace="outreach",
                    metadata={"prospect_id": prospect.id, "auto_queued": True},
                )
                outreach_task.queue()
                self.task_store.save_task(outreach_task)
            except Exception:
                pass


        signal_lines = "\n".join(
            f"  [{s.strength}] {s.description}" for s in prospect.pain_signals
        ) or "  None detected"

        return (
            f"Prospect researched: {prospect.firm_name}\n"
            f"ID: {prospect.id}\n"
            f"Verdict: {prospect.verdict} ({prospect.verdict_label()}) — confidence {prospect.confidence}%\n"
            f"Software stack: {prospect.software_stack}\n"
            f"Financial value: {prospect.financial_value.display()}\n"
            f"Pain signals:\n{signal_lines}\n"
            f"Score: {prospect.total_score}/20 "
            f"(pain={prospect.pain_score} value={prospect.value_score} "
            f"urgency={prospect.urgency_score} repeat={prospect.repeatability_score})\n"
            f"Status: {prospect.status} | Priority: {prospect.priority}"
        )

    async def execute_batch_hunt(
        self,
        firms: str = "",
    ) -> str:
        """Research a list of firms in sequence and return ranked results.

        firms: newline- or comma-separated list of entries, each either
               "Firm Name" or "Firm Name | https://website.com"
        """
        if not firms.strip():
            return "Error: provide a newline- or comma-separated list of firm names."

        # Parse entries
        sep = "\n" if "\n" in firms else ","
        raw_entries = [e.strip() for e in firms.split(sep) if e.strip()]
        parsed = []
        for entry in raw_entries:
            if "|" in entry:
                name, _, site = entry.partition("|")
                parsed.append((name.strip(), site.strip()))
            else:
                parsed.append((entry, ""))

        results = []
        for firm_name, website in parsed:
            try:
                outcome = await self.execute_research_prospect(
                    firm_name=firm_name,
                    website=website,
                )
                results.append(outcome)
            except Exception as err:
                results.append(f"FAILED — {firm_name}: {err}")

        # Re-load and sort all batch prospects by score descending
        from capabilities.prospects.service import list_prospects
        all_p = list_prospects()
        batch_names = {name for name, _ in parsed}
        batch = [p for p in all_p if p.firm_name in batch_names]
        batch.sort(key=lambda p: (0 if p.verdict == "A" else 1 if p.verdict == "B" else 2, -p.total_score))

        summary_lines = ["\n═══ BATCH HUNT RESULTS (ranked by score) ═══"]
        for p in batch:
            fv = p.financial_value.display() if p.financial_value else "unknown"
            summary_lines.append(
                f"  {p.verdict} ({p.total_score}/20) {p.firm_name} — {fv}"
            )
        if not batch:
            summary_lines.append("  No batch prospects found in store.")

        return "\n".join(results) + "\n" + "\n".join(summary_lines)

    async def execute_curate_prospects(
        self,
        dry_run: bool = False,
    ) -> str:
        """Scan all prospects for junk/generic firm names and fix them from the
        website's SITE_TITLE. Removes unfixable single-word / keyword-only names
        so the prospect pool stays clean.

        Args:
            dry_run: If True, report what would change without saving.
        """
        import re as _cr
        from capabilities.prospects.service import list_prospects, save_prospect
        from capabilities.web.research import scrape_web_page_stealth

        _JUNK_PAT = _cr.compile(
            r"^(?:home|contact|about|welcome|services|news|blog|menu|login|"
            r"search|results|directory|index)$"
            r"|^(?:local\s+)?(?:chartered\s+)?(?:accountants?|accountancy|"
            r"accountanc(?:y|ies)|bookkeepers?|bookkeeping|"
            r"tax\s+(?:advisors?|services?|specialists?|accountants?))"
            r"(?:\s+[\w\s]*)?$"
            r"|^[\w][\w\s]{1,30}\s+(?:chartered\s+)?(?:accountants?|"
            r"accountancy|bookkeepers?|bookkeeping|"
            r"tax\s+(?:advisors?|services?|specialists?))s?$",
            _cr.IGNORECASE,
        )
        _SEP = _cr.compile(r"\s*(?:\s[-\u2013\u2014]\s|\|).*$")

        def _domain_brand(website: str) -> str:
            _d = _cr.sub(r"https?://(www\.)?", "", website).split("/")[0]
            _base = _d.split(".")[0]
            return _base.replace("-", " ").replace("_", " ").strip().title()

        all_prospects = list_prospects()
        fixed, unfixable, skipped = [], [], []

        for p in all_prospects:
            if not _JUNK_PAT.match(p.firm_name.strip()):
                skipped.append(p.firm_name)
                continue

            new_name = None
            # Try SITE_TITLE from website scrape
            if p.website:
                try:
                    scraped = await scrape_web_page_stealth(p.website)
                    m = _cr.match(r"SITE_TITLE:\s*(.+)", scraped)
                    if m:
                        candidate = _SEP.sub("", m.group(1)).strip()
                        if (
                            candidate
                            and len(candidate) >= 3
                            and not _JUNK_PAT.match(candidate)
                        ):
                            new_name = candidate
                except Exception:
                    pass
                # Fall back to domain-derived name
                if not new_name:
                    derived = _domain_brand(p.website)
                    if derived and len(derived) >= 3 and not _JUNK_PAT.match(derived):
                        new_name = derived

            if new_name:
                fixed.append(f"{p.firm_name!r} → {new_name!r}")
                if not dry_run:
                    p.firm_name = new_name
                    save_prospect(p)
            else:
                unfixable.append(p.firm_name)

        mode = "[DRY RUN] " if dry_run else ""
        lines = [f"{mode}Prospect curation complete."]
        if fixed:
            lines.append(f"\nFixed ({len(fixed)}):")
            lines.extend(f"  • {f}" for f in fixed)
        if unfixable:
            lines.append(f"\nCould not fix ({len(unfixable)}) — no reliable name source:")
            lines.extend(f"  • {u!r}" for u in unfixable)
        lines.append(f"\nClean prospects skipped: {len(skipped)}")
        return "\n".join(lines)

    async def execute_purge_directory_prospects(
        self,
        dry_run: bool = False,
    ) -> str:
        """Scan all prospects and delete any whose website is a directory,
        aggregator, job board, or listing site rather than a real firm website.

        Args:
            dry_run: If True, report what would be deleted without deleting.
        """
        # RULE: prospect deletion NEVER touches time savings.
        # Hours saved are immutable unless Kane explicitly calls remove_time_saved.
        from capabilities.prospects.service import list_prospects, delete_prospect

        all_prospects = list_prospects()
        to_delete = []

        dir_url_fragments = [
            "/business-directory/", "/find-an-accountant", "/directory/",
            "/search?", "/results?", "/listings/", "/find/",
            "/accountants-near", "/accountants-in", "/category/",
        ]

        for p in all_prospects:
            site = (p.website or "").lower().rstrip("/")
            domain = site.replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0]
            if (
                domain in [d.lower() for d in DISCOVERY_DIRECTORY_DOMAINS]
                or any(frag in site for frag in dir_url_fragments)
            ):
                to_delete.append(p)

        if not to_delete:
            return "No directory/aggregator prospects found — prospect pool is clean."

        mode = "[DRY RUN] " if dry_run else ""
        lines = [f"{mode}Purging {len(to_delete)} directory/aggregator prospects:"]
        for p in to_delete:
            lines.append(f"  • {p.firm_name} ({p.website}) — verdict {p.verdict}")
            if not dry_run:
                try:
                    delete_prospect(p.id)
                except Exception as exc:
                    lines.append(f"    ⚠ Could not delete: {exc}")

        return "\n".join(lines)

    async def execute_librarian_run(self) -> str:
        """Scheduled Librarian run: purge directories, curate names, write vault note."""
        from datetime import datetime, timezone
        from capabilities.prospects.service import list_prospects as _lp  # noqa: F401

        def _lib_task(step: str) -> Task:
            return Task(
                title=f"Scheduled Librarian Run — {step}",
                description="Automated curation step.",
                workspace="library",
                metadata={"agent": "Librarian"},
            )

        purge_text = "(skipped)"
        curate_text = "(skipped)"

        try:
            purge_text = str(
                await self.execute_tool_for_task_async(
                    _lib_task("purge"), "purge_directory_prospects", {"dry_run": False}, source="scheduler"
                )
            )
            print(f"[Librarian] purge: {purge_text[:200]}")
        except Exception as exc:
            purge_text = f"Purge error: {exc}"
            print(f"[Librarian] purge FAILED: {exc}")

        try:
            curate_text = str(
                await self.execute_tool_for_task_async(
                    _lib_task("curate"), "curate_prospects", source="scheduler"
                )
            )
            print(f"[Librarian] curate: {curate_text[:200]}")
        except Exception as exc:
            curate_text = f"Curate error: {exc}"
            print(f"[Librarian] curate FAILED: {exc}")

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        note = (
            f"# Curation Run — {now}\n\n"
            f"## Purged Directories\n{purge_text}\n\n"
            f"## Curation\n{curate_text}\n\n"
            f"*Auto-generated by Librarian every 2 hours.*"
        )

        try:
            await self.execute_tool_for_task_async(
                _lib_task("vault-write"),
                "write_obsidian_note",
                {"filename": "Curation Log", "content": note},
                source="scheduler",
            )
        except Exception as exc:
            return f"Librarian run done but vault write failed: {exc}"

        return f"Librarian run complete — {now}"

    async def execute_maya_backlog_run(self) -> str:
        """Scheduled Maya run: draft outreach for all Grade A prospects without copy."""
        from capabilities.prospects.service import list_prospects

        all_prospects = list_prospects()
        targets = [p for p in all_prospects if p.verdict == "A" and not p.outreach_email]

        if not targets:
            return "Maya backlog run: no Grade A prospects without outreach copy — nothing to do."

        task = Task(
            title="Maya Backlog Run",
            description=f"Draft outreach for {len(targets)} Grade A prospect(s) without copy.",
            workspace="outreach",
            metadata={"agent": "Maya"},
        )

        drafted: list[str] = []
        failed: list[str] = []

        for p in targets:
            try:
                await self.execute_tool_for_task_async(
                    task, "draft_outreach", {"prospect_id": p.id}, source="scheduler"
                )
                drafted.append(p.firm_name)
            except Exception as exc:
                failed.append(f"{p.firm_name}: {exc}")

        lines = [f"Maya backlog run: drafted {len(drafted)}, failed {len(failed)}."]
        if drafted:
            lines.append("Drafted: " + ", ".join(drafted))
        if failed:
            lines.append("Failed: " + "; ".join(failed))
        return "\n".join(lines)

    async def execute_list_prospects(
        self,
        status: Optional[str] = None,
    ) -> str:
        """List all researched prospects, optionally filtered by status."""
        from capabilities.prospects.service import list_prospects

        prospects = list_prospects(status=status)
        if not prospects:
            return "No prospects found."

        lines = []
        for p in prospects:
            score_str = f"{p.total_score}/20" if p.total_score else "unscored"
            sig_count = len(p.pain_signals)
            lines.append(
                f"[{p.verdict}] {p.firm_name} — {p.verdict_label()} | "
                f"score {score_str} | {sig_count} signal(s) | "
                f"stack: {p.software_stack or 'unknown'} | "
                f"status: {p.status} (ID: {p.id})"
            )
        return "\n".join(lines)

    async def execute_get_prospect(
        self,
        prospect_id: str = "",
    ) -> str:
        """Retrieve full detail of a single Prospect by ID."""
        from capabilities.prospects.service import get_prospect

        if not prospect_id:
            return "Error: prospect_id is required."

        prospect = get_prospect(prospect_id)
        if prospect is None:
            return f"Prospect '{prospect_id}' not found."

        return (
            f"Firm: {prospect.firm_name}\n"
            f"Website: {prospect.website or 'not recorded'}\n"
            f"Staff count: {prospect.staff_count}\n"
            f"Services: {prospect.services}\n"
            f"Software stack: {prospect.software_stack}\n"
            f"Pain signals: {prospect.pain_signals}\n"
            f"Priority: {prospect.priority} | Status: {prospect.status}\n"
            f"Researched: {prospect.researched_at}\n"
            f"Notes: {prospect.notes[:200] if prospect.notes else 'none'}"
        )

    async def execute_draft_outreach(
        self,
        prospect_id: str = "",
    ) -> str:
        """Draft a personalised cold email and LinkedIn DM for a prospect.

        Phase 25: Outreach Drafting Engine.
        Loads the prospect profile, uses the LLM (via self.chat) to generate
        a personalised cold email and LinkedIn DM anchored in the Kaido Studios
        offer, then stores the drafts back in the prospect record.
        """
        from capabilities.prospects.service import get_prospect, get_prospect_by_name, save_outreach

        if not prospect_id:
            return "Error: prospect_id is required."

        # Accept either a prospect ID or a firm name
        prospect = get_prospect(prospect_id)
        if prospect is None:
            prospect = get_prospect_by_name(prospect_id)
        if prospect is None:
            return f"No prospect found matching '{prospect_id}'. Try 'list prospects' to see IDs."

        task = Task(
            title=f"Draft outreach: {prospect.firm_name[:45]}",
            description=f"prospect_id={prospect_id}",
            workspace="outreach",
        )
        task.queue()
        self.task_store.save_task(task)
        task.assign("arnie")
        task.start()
        self.task_store.save_task(task)

        from core.config import (
            KAIDO_SENDER_NAME,
            KAIDO_SENDER_TITLE,
            KAIDO_SENDER_COMPANY,
            KAIDO_SENDER_EMAIL,
            KAIDO_SENDER_LINKEDIN,
        )

        contact_line = (
            KAIDO_SENDER_EMAIL
            if KAIDO_SENDER_EMAIL
            else (
                f"LinkedIn: {KAIDO_SENDER_LINKEDIN}"
                if KAIDO_SENDER_LINKEDIN
                else "Reply to this message to arrange a time."
            )
        )

        sig = (
            f"{KAIDO_SENDER_NAME}\n"
            f"{KAIDO_SENDER_TITLE}, {KAIDO_SENDER_COMPANY}"
        )

        system_prompt = (
            "You are a cold outreach copywriter for Kaido Studios.\n\n"

            "# WHAT KAIDO STUDIOS DOES\n"
            "We help UK independent accountancy practices (1-10 staff) replace "
            "manual processes with AI automation — freeing 10+ hours a week "
            "without changing their software stack.\n\n"

            "# THE OFFER\n"
            "A free 30-minute call where we identify their biggest time drain "
            "and give a clear recommendation. No pitch, no obligation.\n\n"

            "# COPYWRITING RULES — follow these exactly\n"
            "1. Never open with \'I\'. Open with an observation about THEM.\n"
            "2. One specific hook from their research — name the signal "
            "(hiring pressure, a software they use, a service they offer). "
            "Do not make generic claims.\n"
            "3. Bridge in one sentence: what that signal tells you.\n"
            "4. Outcome not feature: \'reclaim time on X process\' not \'AI automation\'.\n"
            "5. One ask only: a 30-minute call. No alternatives, no links, no lists.\n"
            "6. UK professional register — measured, direct, no American hype.\n"
            "7. BANNED words and phrases: \'I\'d love to\', \'excited\', "
            "\'game-changing\', \'AI-powered\', \'leverage\', \'help you grow\', "
            "\'save you time\', \'let me\', any exclamation mark.\n"
            "8. Email body: under 130 words. LinkedIn DM: under 90 words.\n"
            "9. Sign every email exactly like this (no changes):\n"
            f"{sig}\n\n"

            "# OUTPUT FORMAT — use these exact delimiters, nothing else\n"
            "=== EMAIL SUBJECT ===\n"
            "<subject line — specific to this firm, under 8 words>\n"
            "=== EMAIL BODY ===\n"
            "<email body — opens with them, ends with a single CTA line and the sig above>\n"
            "=== LINKEDIN DM ===\n"
            "<linkedin dm — one hook, one ask, no sign-off needed>"
        )

        # Format pain signals as clean text
        oi = prospect.outreach_intel
        pain_lines = "\n".join(
            f"  [{s.strength}] {s.description}"
            for s in (prospect.pain_signals or [])
        ) or "  None detected"
        objections_str = (
            "\n".join(f"  - {o}" for o in (oi.objections or []))
            if oi.objections else "  None noted"
        )

        user_message = (
            f"Draft outreach for this prospect:\n\n"
            f"Firm: {prospect.firm_name}\n"
            f"Website: {prospect.website or 'not listed'}\n"
            f"Niche / sector: {prospect.niche or 'general practice'}\n"
            f"Software stack: {prospect.software_stack or 'unknown'}\n"
            f"Services: {prospect.services or 'not listed'}\n"
            f"\n"
            f"PAIN SIGNALS (use one of these as your hook):\n{pain_lines}\n"
            f"\n"
            f"OUTREACH INTELLIGENCE:\n"
            f"Why now: {oi.why_now or 'not specified'}\n"
            f"Suggested angle: {oi.outreach_angle or 'not specified'}\n"
            f"Likely objections to pre-empt:\n{objections_str}\n"
            f"\n"
            f"Use the strongest OBSERVED or INDICATED pain signal as your opening hook. "
            f"Follow the suggested angle where it fits. "
            f"Do NOT directly name the objections — neutralise them by framing the offer correctly.\n\n"
            f"Generate the email subject, email body, and LinkedIn DM."
        )

        try:
            response = await self.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                model=DEFAULT_MODEL,
                capability="outreach",
                source="execute_draft_outreach",
            )
        except Exception as err:
            task.fail(str(err))
            self.task_store.save_task(task)
            raise

        # Parse response into sections
        import re as _re
        email_subject = ""
        email_body = ""
        linkedin_dm = ""

        subject_match = _re.search(
            r"=== EMAIL SUBJECT ===\s*(.+?)\s*=== EMAIL BODY ===",
            response, _re.DOTALL
        )
        body_match = _re.search(
            r"=== EMAIL BODY ===\s*(.+?)\s*=== LINKEDIN DM ===",
            response, _re.DOTALL
        )
        dm_match = _re.search(
            r"=== LINKEDIN DM ===\s*(.+?)$",
            response, _re.DOTALL
        )

        if subject_match:
            email_subject = subject_match.group(1).strip()
        if body_match:
            email_body = body_match.group(1).strip()
        if dm_match:
            linkedin_dm = dm_match.group(1).strip()

        # Fallback: store raw response if parsing fails
        if not email_body:
            email_body = response
            email_subject = f"Quick question — {prospect.firm_name}"

        full_email = f"Subject: {email_subject}\n\n{email_body}"
        save_outreach(prospect_id, outreach_email=full_email, outreach_dm=linkedin_dm)

        task.begin_verification()
        self.task_store.save_task(task)
        task.complete(TaskResult(success=True, output=prospect_id))
        self.task_store.save_task(task)

        return (
            f"Outreach drafted for {prospect.firm_name}\n\n"
            f"📧 EMAIL\nSubject: {email_subject}\n\n{email_body}\n\n"
            f"💼 LINKEDIN DM\n{linkedin_dm}\n\n"
            f"Saved to prospect record. Review before sending."
        )

    async def execute_log_savings_baseline(
        self,
        client_id: str = "",
        process_name: str = "",
        minutes_per_run: float = 0.0,
        runs_per_month: float = 0.0,
        staff_hourly_rate: float = 0.0,
    ) -> str:
        """Log a before-state process baseline through the Savings capability Tool boundary.

        Phase 26: Savings Baseline Logger.
        Baseline logging is tracked as a first-class Task (workspace="client"),
        following the same pattern as add_client and update_client_status. The
        actual JSON persistence is delegated to capabilities.savings.service so
        core/ never touches the savings baseline store file directly.
        """
        from capabilities.savings.service import log_baseline

        if not client_id or not process_name:
            return "Error: client_id and process_name are required."

        task = Task(
            title=f"Log savings baseline: {process_name[:50]}",
            description=f"client_id={client_id}",
            workspace="client",
        )
        task.queue()
        self.task_store.save_task(task)

        task.assign("nero")
        task.start()
        self.task_store.save_task(task)

        try:
            baseline = log_baseline(
                client_id=client_id,
                process_name=process_name,
                minutes_per_run=minutes_per_run,
                runs_per_month=runs_per_month,
                staff_hourly_rate=staff_hourly_rate,
            )
        except Exception as err:
            task.fail(str(err))
            self.task_store.save_task(task)
            raise

        task.begin_verification()
        self.task_store.save_task(task)

        task.complete(
            TaskResult(
                success=True,
                output=baseline.id,
            )
        )
        self.task_store.save_task(task)

        return (
            f"Baseline logged: {baseline.process_name} "
            f"(ID: {baseline.id})\n"
            f"{baseline.minutes_per_run} min/run × {baseline.runs_per_month} runs/mo "
            f"@ £{baseline.staff_hourly_rate}/hr\n"
            f"Baseline monthly cost: £{baseline.baseline_monthly_cost:.2f}"
        )

    async def execute_list_savings_baselines(
        self,
        client_id: str = "",
    ) -> str:
        """Execute the canonical list_savings_baselines Tool as a human-readable summary."""
        from capabilities.savings.service import list_baselines

        baselines = list_baselines(client_id=client_id or None)

        if not baselines:
            return "No savings baselines found."

        lines = [
            f"- {b.process_name}: {b.minutes_per_run} min/run × "
            f"{b.runs_per_month} runs/mo @ £{b.staff_hourly_rate}/hr "
            f"= £{b.baseline_monthly_cost:.2f}/mo (ID: {b.id})"
            for b in baselines
        ]
        return "\n".join(lines)

    async def execute_log_automation_run(
        self,
        client_id: str = "",
        process_name: str = "",
        baseline_id: str = "",
        duration_seconds: float = 0.0,
    ) -> str:
        """Log an automation run through the Automation log capability Tool boundary.

        Phase 27: Automation Activity Logger.
        Run logging is tracked as a first-class Task (workspace="client"),
        following the same pattern as log_savings_baseline. The actual JSON
        persistence and minutes-saved calculation is delegated to
        capabilities.automation_log.service.
        """
        from capabilities.automation_log.service import log_run

        if not client_id or not process_name or not baseline_id:
            return "Error: client_id, process_name, and baseline_id are required."

        task = Task(
            title=f"Log automation run: {process_name[:50]}",
            description=f"client_id={client_id}, baseline_id={baseline_id}",
            workspace="client",
        )
        task.queue()
        self.task_store.save_task(task)

        task.assign("nero")
        task.start()
        self.task_store.save_task(task)

        try:
            run = log_run(
                client_id=client_id,
                process_name=process_name,
                baseline_id=baseline_id,
                duration_seconds=duration_seconds,
            )
        except Exception as err:
            task.fail(str(err))
            self.task_store.save_task(task)
            raise

        task.begin_verification()
        self.task_store.save_task(task)

        task.complete(
            TaskResult(
                success=True,
                output=run.id,
            )
        )
        self.task_store.save_task(task)

        return (
            f"Automation run logged: {run.process_name} "
            f"(ID: {run.id})\n"
            f"Duration: {run.duration_seconds:.0f}s | "
            f"Minutes saved: {run.minutes_saved:.1f}"
        )

    async def execute_get_monthly_automation_summary(
        self,
        client_id: str = "",
        year: int = 0,
        month: int = 0,
    ) -> str:
        """Execute the canonical get_monthly_automation_summary Tool as a human-readable summary."""
        from capabilities.automation_log.service import monthly_summary

        if not client_id or not year or not month:
            return "Error: client_id, year, and month are required."

        summary = monthly_summary(client_id=client_id, year=year, month=month)

        return (
            f"Automation summary for {client_id} — {summary['year']}-{summary['month']:02d}\n"
            f"Total runs: {summary['total_runs']}\n"
            f"Total minutes saved: {summary['total_minutes_saved']}\n"
            f"Total £ saved: £{summary['total_gbp_saved']}"
        )

    async def execute_get_client(
        self,
        client_id: str = "",
    ) -> str:
        """Retrieve full detail of a single Client by ID."""
        from capabilities.clients.service import get_client

        if not client_id:
            return "Error: client_id is required."

        client = get_client(client_id)
        if client is None:
            return f"Client '{client_id}' not found."

        return (
            f"Name: {client.name}\n"
            f"Service: {client.service}\n"
            f"Status: {client.status}\n"
            f"Created: {client.created_at}\n"
            f"Notes: {client.notes[:200] if client.notes else 'none'}"
        )

    @staticmethod
    def _determine_billing_mode(
        client: Any,
        *,
        year: int,
        month: int,
        documented_savings: float,
    ) -> tuple[str, float]:
        """Shared Kaido Studios retainer billing logic.

        Months 1-3 of the client relationship (counted from client.created_at)
        bill a fixed £750/mo retainer. From month 4 onward, billing switches
        to 20% of that month's documented £ savings, with a £750 floor.
        Shared by execute_generate_savings_report and
        execute_get_client_dashboard so both always agree on the current
        retainer amount.
        """
        from datetime import datetime

        created = datetime.fromisoformat(client.created_at)
        months_active = (year - created.year) * 12 + (month - created.month) + 1

        if months_active <= 3:
            return (
                f"Fixed retainer (month {months_active} of onboarding)",
                750.0,
            )

        return (
            "20% of documented savings",
            max(750.0, documented_savings * 0.20),
        )

    async def execute_generate_savings_report(
        self,
        client_id: str = "",
        year: int = 0,
        month: int = 0,
    ) -> str:
        """Generate a monthly savings report and retainer invoice for a client.

        Phase 28: Monthly Savings Report.
        Loads the client, that month's automation summary, and every logged
        baseline; determines billing mode (fixed £750/mo retainer for the
        first 3 months of the client relationship, 20% of that month's
        documented £ savings — minimum £750 — from month 4 onward); uses
        self.chat() with a Nero-authored prompt to write a professional
        HTML report plus a plain-text retainer invoice; saves the HTML
        report to data/reports/{client_id}_{year}_{month}.html.
        """
        import os
        import re as _re
        from capabilities.clients.service import get_client
        from capabilities.automation_log.service import monthly_summary
        from capabilities.savings.service import list_baselines

        if not client_id or not year or not month:
            return "Error: client_id, year, and month are required."

        client = get_client(client_id)
        if client is None:
            return f"Client '{client_id}' not found."

        summary = monthly_summary(client_id=client_id, year=year, month=month)
        baselines = list_baselines(client_id=client_id)

        billing_mode, retainer_amount = self._determine_billing_mode(
            client, year=year, month=month,
            documented_savings=summary["total_gbp_saved"],
        )

        task = Task(
            title=f"Generate savings report: {client.name[:40]} — {year}-{month:02d}",
            description=f"client_id={client_id}",
            workspace="client",
        )
        task.queue()
        self.task_store.save_task(task)
        task.assign("nero")
        task.start()
        self.task_store.save_task(task)

        baseline_lines = "\n".join(
            f"- {b.process_name}: {b.minutes_per_run} min/run × "
            f"{b.runs_per_month} runs/mo @ £{b.staff_hourly_rate}/hr "
            f"= £{b.baseline_monthly_cost:.2f}/mo baseline cost"
            for b in baselines
        ) or "No baselines logged yet."

        system_prompt = (
            "You are Nero, the client success agent for Kaido Studios. "
            "Write a professional, client-facing monthly savings report as a "
            "complete, standalone HTML document (including <html>, <head> with "
            "inline <style>, and <body>), and a separate plain-text retainer "
            "invoice. Be transparent and methodical — reference only the actual "
            "figures given below; never invent numbers.\n\n"
            "Output format — use these exact delimiters, nothing else:\n"
            "=== REPORT HTML ===\n"
            "<full HTML document>\n"
            "=== INVOICE TEXT ===\n"
            "<plain-text invoice>"
        )

        user_message = (
            f"Generate the monthly savings report and retainer invoice for this "
            f"client.\n\n"
            f"Client: {client.name}\n"
            f"Service: {client.service}\n"
            f"Status: {client.status}\n"
            f"Report period: {year}-{month:02d}\n\n"
            f"Automation summary for this month:\n"
            f"- Total automation runs: {summary['total_runs']}\n"
            f"- Total minutes saved: {summary['total_minutes_saved']}\n"
            f"- Total £ saved: £{summary['total_gbp_saved']}\n\n"
            f"Logged process baselines:\n{baseline_lines}\n\n"
            f"Billing mode: {billing_mode}\n"
            f"Retainer amount due: £{retainer_amount:.2f}\n\n"
            f"Generate the HTML report and the invoice text."
        )

        try:
            response = await self.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                model=DEFAULT_MODEL,
                capability="savings_report",
                source="execute_generate_savings_report",
            )
        except Exception as err:
            task.fail(str(err))
            self.task_store.save_task(task)
            raise

        html_match = _re.search(
            r"=== REPORT HTML ===\s*(.+?)\s*=== INVOICE TEXT ===",
            response, _re.DOTALL,
        )
        invoice_match = _re.search(
            r"=== INVOICE TEXT ===\s*(.+?)$",
            response, _re.DOTALL,
        )

        report_html = html_match.group(1).strip() if html_match else response
        invoice_text = (
            invoice_match.group(1).strip()
            if invoice_match
            else (
                f"Kaido Studios — Retainer Invoice\n"
                f"Client: {client.name}\n"
                f"Period: {year}-{month:02d}\n"
                f"Billing mode: {billing_mode}\n"
                f"Amount due: £{retainer_amount:.2f}"
            )
        )

        reports_dir = os.path.join("data", "reports")
        os.makedirs(reports_dir, exist_ok=True)
        report_path = os.path.join(reports_dir, f"{client_id}_{year}_{month}.html")

        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_html)

        task.begin_verification()
        self.task_store.save_task(task)
        task.complete(TaskResult(success=True, output=report_path))
        self.task_store.save_task(task)

        return (
            f"Savings report generated for {client.name} — {year}-{month:02d}\n"
            f"Report saved to: {report_path}\n\n"
            f"--- RETAINER INVOICE ---\n{invoice_text}"
        )

    async def execute_get_client_dashboard(self) -> str:
        """Build a structured status dashboard across every active client.

        Phase 29: Client Status Dashboard.
        For each active client: this calendar month's automation summary,
        total £ savings to date (all-time, not just this month), the
        current retainer amount (same billing-mode logic as
        execute_generate_savings_report, via _determine_billing_mode), and
        status. Returned as a JSON string.
        """
        import json as _json
        from datetime import datetime, timezone
        from capabilities.clients.service import list_clients
        from capabilities.automation_log.service import (
            monthly_summary,
            total_savings_to_date,
        )

        now = datetime.now(timezone.utc)
        active_clients = list_clients(status="active")

        clients_summary = []
        for client in active_clients:
            summary = monthly_summary(
                client_id=client.id, year=now.year, month=now.month
            )
            to_date = total_savings_to_date(client.id)
            billing_mode, retainer_amount = self._determine_billing_mode(
                client, year=now.year, month=now.month,
                documented_savings=summary["total_gbp_saved"],
            )

            clients_summary.append(
                {
                    "client_id": client.id,
                    "name": client.name,
                    "service": client.service,
                    "status": client.status,
                    "latest_monthly_summary": summary,
                    "total_savings_to_date_gbp": to_date["total_gbp_saved"],
                    "current_retainer_amount_gbp": round(retainer_amount, 2),
                    "billing_mode": billing_mode,
                }
            )

        return _json.dumps(
            {
                "generated_at": now.isoformat(),
                "active_client_count": len(clients_summary),
                "clients": clients_summary,
            },
            indent=2,
        )

    def list_staged_artifacts(self) -> Dict[str, Dict[str, Any]]:
        """List Swarm artifacts awaiting approval through the Swarm capability."""
        return self.swarm_orchestrator.list_staged_artifacts()

    def get_latest_staged_artifact(self) -> Optional[Dict[str, Any]]:
        """Return the most recently staged Swarm artifact, if any."""
        return self.swarm_orchestrator.get_latest_staged_artifact()

    def approve_staged_artifact(
        self,
        task_id: str,
        target_filename: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Approve and commit a staged Swarm artifact through the Swarm capability."""
        return self.swarm_orchestrator.approve_staged_artifact(task_id, target_filename)

    def reject_staged_artifact(self, task_id: str) -> bool:
        """Discard a staged Swarm artifact through the Swarm capability."""
        return self.swarm_orchestrator.reject_staged_artifact(task_id)

    # ---------------------------------------------------------------------
    # Agent selection
    # ---------------------------------------------------------------------

    def select_agent(
        self,
        task: Task,
        agent_name: Optional[str] = None,
    ) -> Agent:
        """
        Select an Agent for a Task.

        Selection order:

            1. Explicit Agent name
            2. Task assigned_agent
            3. Task metadata capability
            4. Task metadata agent
            5. Fallback to Coordinator
        """

        # --------------------------------------------------------------
        # Explicit Agent selection
        # --------------------------------------------------------------

        if agent_name:
            agent = self.agents.find_by_name(agent_name)

            if agent is None:
                raise ValueError(
                    f"Agent '{agent_name}' was not found."
                )

            return agent

        # --------------------------------------------------------------
        # Task assignment
        # --------------------------------------------------------------

        if task.assigned_agent:
            try:
                return self.agents.get(task.assigned_agent)
            except KeyError:
                # The assigned value might be a human-readable Agent name.
                agent = self.agents.find_by_name(
                    task.assigned_agent
                )

                if agent is not None:
                    return agent

                raise ValueError(
                    f"Assigned Agent '{task.assigned_agent}' "
                    f"was not found."
                )

        # --------------------------------------------------------------
        # Capability-based selection
        # --------------------------------------------------------------

        capability = task.metadata.get("agent_capability")

        if capability:
            candidates = self.agents.find_by_capability(
                capability
            )

            available = [
                agent
                for agent in candidates
                if agent.status == AgentStatus.IDLE
            ]

            if available:
                return available[0]

            if candidates:
                return candidates[0]

        # --------------------------------------------------------------
        # Explicit metadata Agent
        # --------------------------------------------------------------

        metadata_agent = task.metadata.get("agent")

        if metadata_agent:
            agent = self.agents.find_by_name(
                metadata_agent
            )

            if agent is not None:
                return agent

        # --------------------------------------------------------------
        # Workspace-based selection
        # --------------------------------------------------------------

        if task.workspace:
            workspace_agent = self.agents.find_by_workspace(task.workspace)

            if workspace_agent is not None:
                return workspace_agent

        # --------------------------------------------------------------
        # Default
        # --------------------------------------------------------------

        coordinator = self.agents.find_by_name(
            "Coordinator"
        )

        if coordinator is None:
            raise RuntimeError(
                "No Coordinator Agent is registered."
            )

        return coordinator

    # ---------------------------------------------------------------------
    # Model provider selection
    # ---------------------------------------------------------------------

    def select_model_provider(
        self,
        agent: Optional[Agent] = None,
    ) -> ModelProvider:
        """
        Select a ModelProvider for an Agent.

        Routing strategy:
        - Prefer OmniRoute when registered and healthy — it proxies the
          user\'s Claude subscription and handles complex reasoning, tool
          synthesis, and conversation far better than the local 8b model.
        - Fall back to Ollama (hermes3:8b) if OmniRoute is unavailable,
          keeping cost at near-zero when offline.
        """

        providers = self.models.list_providers()

        if not providers:
            raise RuntimeError(
                "No Model Providers are registered."
            )

        # Prefer OmniRoute when available and healthy
        if "omniroute" in providers:
            try:
                omniroute = self.models.get("omniroute")
                if omniroute.health_check():
                    return omniroute
            except Exception:
                pass

        # Fallback: first registered provider (Ollama / hermes3:8b)
        return self.models.get(providers[0])

    # ---------------------------------------------------------------------
    # Model interface
    # ---------------------------------------------------------------------

    @staticmethod
    def _coerce_model_messages(messages: List[Any]) -> List[ModelMessage]:
        """Convert interface message dictionaries into canonical messages."""
        result: List[ModelMessage] = []

        for message in messages:
            if isinstance(message, ModelMessage):
                result.append(message)
                continue

            if not isinstance(message, dict):
                raise TypeError(
                    "Model messages must be ModelMessage objects or dictionaries."
                )

            result.append(
                ModelMessage(
                    role=str(message["role"]),
                    content=str(message["content"]),
                    name=message.get("name"),
                )
            )

        return result

    async def chat(
        self,
        messages: List[Any],
        model: Optional[str] = None,
        capability: str = "conversation",
        source: str = "harness.chat",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Execute a non-streaming model request through AgenticOS."""
        task = Task(
            title="Model chat",
            description="Execute a conversational model request.",
            workspace="development",
            metadata={
                "source": source,
                "capability": capability,
            },
        )
        agent = self.select_agent(task)
        provider = self.select_model_provider(agent)
        selected_model = model or agent.preferred_model()

        request_metadata = dict(metadata or {})
        request_metadata.update({
            "source": source,
            "capability": capability,
        })

        request = ModelRequest(
            messages=self._coerce_model_messages(messages),
            capability=capability,
            model=selected_model,
            metadata=request_metadata,
        )

        try:
            response = await asyncio.to_thread(provider.chat, request)
        except Exception as _exc:
            _fallback = "ollama"
            if provider.name != _fallback and _fallback in self.models.list_providers():
                import logging as _log
                _log.getLogger(__name__).warning(
                    "Provider '%s' failed (%s) — falling back to '%s'",
                    provider.name, _exc, _fallback,
                )
                _fb_provider = self.models.get(_fallback)
                response = await asyncio.to_thread(_fb_provider.chat, request)
            else:
                raise
        return response.content

    def stream(
        self,
        messages: List[Any],
        model: Optional[str] = None,
        capability: str = "conversation",
        source: str = "harness.stream",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Return a provider-independent model stream through AgenticOS."""
        task = Task(
            title="Model stream",
            description="Execute a streaming conversational model request.",
            workspace="development",
            metadata={
                "source": source,
                "capability": capability,
            },
        )
        agent = self.select_agent(task)
        provider = self.select_model_provider(agent)
        selected_model = model or agent.preferred_model()

        request_metadata = dict(metadata or {})
        request_metadata.update({
            "source": source,
            "capability": capability,
        })

        request = ModelRequest(
            messages=self._coerce_model_messages(messages),
            capability=capability,
            model=selected_model,
            metadata=request_metadata,
        )

        return provider.stream(request)

    # ---------------------------------------------------------------------
    # Tool execution and post-tool routing
    # ---------------------------------------------------------------------

    def _authorize_tool(
        self,
        tool_name: str,
        *,
        task: Task,
        agent: Agent,
        source: str = "harness",
        user_approved: bool = False,
    ):
        """Evaluate Tool authorization without executing the Tool."""
        tool = self.tools.get(tool_name)
        if tool is None:
            raise KeyError(f"Unknown tool: {tool_name}")

        result = self.policy.evaluate(
            PolicyRequest(
                agent=agent,
                task=task,
                tool=tool,
                source=source,
                user_approved=user_approved,
            )
        )

        if result.decision == PolicyDecision.DENY:
            raise PermissionError(
                f"Policy denied Tool '{tool_name}': "
                f"{result.message}"
            )

        return result

    def execute_tool(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        *,
        task: Optional[Task] = None,
        agent: Optional[Agent] = None,
        source: str = "harness",
        user_approved: bool = False,
    ) -> Any:
        """Authorize and execute a registered Tool through the Harness."""
        if task is None or agent is None:
            raise ValueError(
                "Policy-protected Tool execution requires both task and agent. "
                "Use execute_tool_for_task() for a managed execution context."
            )

        self._authorize_tool(
            tool_name,
            task=task,
            agent=agent,
            source=source,
            user_approved=user_approved,
        )

        task.queue()
        task.assign(task.assigned_agent if task.assigned_agent else agent.id)
        task.start()
        self.task_store.save_task(task)

        try:
            output = self.tools.execute(tool_name, arguments)
        except Exception as err:
            task.fail(str(err))
            self.task_store.save_task(task)
            raise

        task.complete(TaskResult(success=True, output=str(output)))
        self.task_store.save_task(task)
        return output

    async def execute_tool_async(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        *,
        task: Optional[Task] = None,
        agent: Optional[Agent] = None,
        source: str = "harness",
        user_approved: bool = False,
    ) -> Any:
        """Async counterpart to policy-protected Tool execution."""
        if task is None or agent is None:
            raise ValueError(
                "Policy-protected Tool execution requires both task and agent. "
                "Use execute_tool_for_task() for a managed execution context."
            )

        self._authorize_tool(
            tool_name,
            task=task,
            agent=agent,
            source=source,
            user_approved=user_approved,
        )

        task.queue()
        task.assign(task.assigned_agent if task.assigned_agent else agent.id)
        task.start()
        self.task_store.save_task(task)

        try:
            output = await self.tools.execute_async(tool_name, arguments)
        except Exception as err:
            task.fail(str(err))
            self.task_store.save_task(task)
            raise

        task.complete(TaskResult(success=True, output=str(output)))
        self.task_store.save_task(task)
        return output

    def execute_tool_for_task(
        self,
        task: Task,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        *,
        agent_name: Optional[str] = None,
        source: str = "harness",
        user_approved: bool = False,
    ) -> Any:
        """Select an Agent, enforce Policy, then execute the Tool."""
        agent = self.select_agent(task, agent_name=agent_name)
        return self.execute_tool(
            tool_name,
            arguments,
            task=task,
            agent=agent,
            source=source,
            user_approved=user_approved,
        )

    async def execute_tool_for_task_async(
        self,
        task: Task,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        *,
        agent_name: Optional[str] = None,
        source: str = "harness",
        user_approved: bool = False,
    ) -> Any:
        """Async managed Tool execution through the Policy boundary."""
        agent = self.select_agent(task, agent_name=agent_name)
        return await self.execute_tool_async(
            tool_name,
            arguments,
            task=task,
            agent=agent,
            source=source,
            user_approved=user_approved,
        )

    def tool_execution_mode(self, tool_name: str) -> str:
        """
        Return the canonical post-execution routing mode.

        The Harness owns this decision. Interfaces such as bot.py must not
        maintain their own hard-coded lists of deterministic tools.
        """
        return self.tools.execution_mode(tool_name)

    # ---------------------------------------------------------------------
    # Voice
    # ---------------------------------------------------------------------

    def record_voice(self) -> bytes:
        """Record local microphone audio through the Voice capability."""
        return self.voice.record()

    def transcribe_voice(self, audio_bytes: bytes) -> str:
        """Transcribe captured audio through the Voice capability."""
        return self.voice.transcribe(audio_bytes)

    def speak_text(self, text: str) -> None:
        """Speak text aloud through the Voice capability's TTS engine."""
        self.voice.speak(text)

    def configure_voice_agent(self, **kwargs) -> Any:
        """Configure the Voice capability's conversational agent."""
        return self.voice.configure_agent(**kwargs)

    # ---------------------------------------------------------------------
    # Memory
    # ---------------------------------------------------------------------

    def initialize_memory(self) -> None:
        """Initialize the configured AgenticOS memory store."""
        self.memory.init_db()

    def initialize_tasks(self) -> None:
        """Initialize the configured AgenticOS Task store and recover any
        Tasks left QUEUED or RUNNING when the process last stopped."""
        self.task_store.init_db()
        self.recover_incomplete_tasks()

    def recover_incomplete_tasks(self) -> int:
        """Re-enqueue Tasks that did not reach a terminal status.

        RUNNING Tasks were interrupted mid-execution and are reset to
        QUEUED. QUEUED Tasks are already durable in the store and require
        no change; both are surfaced here as recovered.
        """
        recovered = self.task_store.recover_interrupted_tasks()
        still_queued = self.task_store.list_tasks(status=TaskStatus.QUEUED.value)
        return recovered + len(still_queued)

    # ---------------------------------------------------------------------
    # Tasks
    # ---------------------------------------------------------------------

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a persisted Task by id through the Task capability."""
        return self.task_store.get_task(task_id)

    def list_tasks(
        self,
        status: Optional[str] = None,
        workspace: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List persisted Tasks through the Task capability."""
        return self.task_store.list_tasks(
            status=status,
            workspace=workspace,
            limit=limit,
        )

    def prune_tasks(self, days: int = 30) -> int:
        """Delete terminal Tasks older than `days` through the Task capability."""
        return self.task_store.delete_terminal_tasks_older_than(days)

    def clear_stale_queued_tasks(self, older_than_minutes: int = 10) -> int:
        """Cancel QUEUED Tasks whose Agent has gone idle without picking them up.

        A Task is normally QUEUED for only a few milliseconds before its
        creator immediately assigns and starts it. A Task still QUEUED after
        `older_than_minutes` means whatever was going to run it never did —
        the process was interrupted, the assigned Agent errored out before
        starting it, or it was never picked up at all. Once that Agent is
        idle (not mid-execution on something else), there is nothing left
        that will ever advance the Task, so it is cancelled rather than left
        cluttering the Queued list forever.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)
        cleared = 0

        for row in self.task_store.list_tasks(status=TaskStatus.QUEUED.value, limit=500):
            created_at = row.get("created_at")
            if not created_at:
                continue
            try:
                created = datetime.fromisoformat(created_at)
            except ValueError:
                continue
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created > cutoff:
                continue  # still fresh — may just be mid-dispatch

            assigned_agent = row.get("assigned_agent")
            if assigned_agent:
                agent = self._find_agent_loosely(assigned_agent)
                if agent is not None and agent.status != AgentStatus.IDLE:
                    continue  # still legitimately being worked

            if self.task_store.cancel_task(
                row["id"],
                reason=f"Cleared: queued longer than {older_than_minutes}m with no active Agent picking it up.",
            ):
                cleared += 1

        return cleared

    def _find_agent_loosely(self, assigned_agent: str) -> Optional[Agent]:
        """Resolve an assigned_agent value that may be an Agent id or a plain name."""
        try:
            return self.agents.get(assigned_agent)
        except KeyError:
            return self.agents.find_by_name(assigned_agent)

    def get_memory(
        self,
        channel_id: str,
        limit: int = 20,
    ) -> List[Dict[str, str]]:
        """Retrieve recent persistent conversation memory."""
        return self.memory.get_recent_history(channel_id, limit)

    def save_memory(
        self,
        channel_id: str,
        user_id: str,
        role: str,
        content: str,
    ) -> None:
        """Persist one conversation message through the memory capability."""
        self.memory.save_message(
            channel_id,
            user_id,
            role,
            content,
        )

    async def compact_memory(
        self,
        channel_id: str,
        keep_recent: int = 10,
    ) -> str:
        """Compact persistent channel memory when requested by the caller."""
        return await self.memory.compact_channel_memory(
            channel_id,
            keep_recent,
        )

    def run_tool(
        self,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute a tool and return structured runtime evidence.

        Deterministic tools are authoritative runtime capabilities and should
        be returned directly. Synthesis-capable tools are explicitly marked
        for later model synthesis by the caller.
        """
        task = Task(
            title=f"Tool execution: {tool_name}",
            description=f"Execute registered Tool '{tool_name}'.",
            workspace="development",
        )
        agent = self.select_agent(task)
        result = self.execute_tool(
            tool_name,
            arguments,
            task=task,
            agent=agent,
            source="harness.run_tool",
        )
        return {
            "tool": tool_name,
            "mode": self.tool_execution_mode(tool_name),
            "result": result,
        }

    # ---------------------------------------------------------------------
    # Task execution
    # ---------------------------------------------------------------------

    def run(
        self,
        task: Task,
        agent_name: Optional[str] = None,
    ) -> HarnessResult:
        """
        Execute one Task through the Harness.

        This is the first complete ARNIE orchestration path.
        """

        execution: Optional[TaskExecution] = None
        response: Optional[ModelResponse] = None

        try:
            # ==========================================================
            # Queue
            # ==========================================================

            if task.status == TaskStatus.CREATED:
                task.queue()

            self.events.publish(
                create_event(
                    name=EventNames.TASK_QUEUED,
                    category=EventCategory.TASK,
                    source="harness",
                    task_id=task.id,
                    correlation_id=task.id,
                    data={
                        "title": task.title,
                    },
                )
            )

            # ==========================================================
            # Agent selection
            # ==========================================================

            agent = self.select_agent(
                task,
                agent_name=agent_name,
            )

            # ==========================================================
            # Assign
            # ==========================================================

            task.assign(task.assigned_agent if task.assigned_agent else agent.id)

            self.events.publish(
                create_event(
                    name=EventNames.TASK_ASSIGNED,
                    category=EventCategory.TASK,
                    source="harness",
                    task_id=task.id,
                    correlation_id=task.id,
                    agent_id=agent.id,
                    data={
                        "agent": agent.name,
                    },
                )
            )

            # ==========================================================
            # Start Agent
            # ==========================================================

            agent.start()

            self.events.publish(
                create_event(
                    name=EventNames.AGENT_STARTED,
                    category=EventCategory.AGENT,
                    source="harness",
                    task_id=task.id,
                    correlation_id=task.id,
                    agent_id=agent.id,
                    data={
                        "agent": agent.name,
                        "role": agent.role,
                    },
                )
            )

            # ==========================================================
            # Start Task
            # ==========================================================

            task.start()

            self.events.publish(
                create_event(
                    name=EventNames.TASK_STARTED,
                    category=EventCategory.TASK,
                    source="harness",
                    task_id=task.id,
                    correlation_id=task.id,
                    agent_id=agent.id,
                )
            )

            # ==========================================================
            # Create Execution
            # ==========================================================

            execution = TaskExecution(
                task_id=task.id,
                agent_id=agent.id,
            )

            execution.start()

            # ==========================================================
            # Select Model Provider
            # ==========================================================

            provider = self.select_model_provider(agent)

            preferred_model = agent.preferred_model()

            execution.provider = provider.name
            execution.model = preferred_model

            # ==========================================================
            # Build Model Request
            # ==========================================================

            system_prompt = agent.system_prompt

            user_prompt = task.description

            if task.inputs:
                user_prompt += (
                    "\n\nTask inputs:\n"
                    f"{self._format_inputs(task.inputs)}"
                )

            request = ModelRequest(
                messages=[
                    ModelMessage(
                        role="system",
                        content=system_prompt,
                    ),
                    ModelMessage(
                        role="user",
                        content=user_prompt,
                    ),
                ],
                capability=agent.model_capability(),
                model=preferred_model,
                metadata={
                    "task_id": task.id,
                    "execution_id": execution.id,
                    "agent_id": agent.id,
                },
            )

            # ==========================================================
            # Model Requested
            # ==========================================================

            self.events.publish(
                create_event(
                    name=EventNames.MODEL_REQUESTED,
                    category=EventCategory.MODEL,
                    source="harness",
                    task_id=task.id,
                    execution_id=execution.id,
                    agent_id=agent.id,
                    correlation_id=task.id,
                    data={
                        "provider": provider.name,
                        "model": preferred_model,
                        "capability": agent.model_capability(),
                    },
                )
            )

            # ==========================================================
            # Execute Model
            # ==========================================================

            try:
                response = provider.chat(request)
            except Exception as _primary_exc:
                # Primary provider failed (e.g. OmniRoute 400/timeout).
                # Fall back to Ollama so ARNIE stays responsive.
                _fallback_name = "ollama"
                if provider.name != _fallback_name and _fallback_name in self.models.list_providers():
                    import logging as _log
                    _log.getLogger(__name__).warning(
                        "Provider '%s' failed (%s) — falling back to '%s'",
                        provider.name, _primary_exc, _fallback_name,
                    )
                    provider = self.models.get(_fallback_name)
                    execution.provider = provider.name
                    response = provider.chat(request)
                else:
                    raise

            # ==========================================================
            # Model Completed
            # ==========================================================

            self.events.publish(
                create_event(
                    name=EventNames.MODEL_COMPLETED,
                    category=EventCategory.MODEL,
                    source=provider.name,
                    task_id=task.id,
                    execution_id=execution.id,
                    agent_id=agent.id,
                    correlation_id=task.id,
                    data={
                        "provider": response.provider,
                        "model": response.model,
                    },
                )
            )

            # ==========================================================
            # Build Task Result
            # ==========================================================

            result = TaskResult(
                success=True,
                output=response.content,
                metadata={
                    "model": response.model,
                    "provider": response.provider,
                },
            )

            # ==========================================================
            # Complete Execution
            # ==========================================================

            execution.complete(result)

            # ==========================================================
            # Verify
            # ==========================================================

            task.begin_verification()

            self.events.publish(
                create_event(
                    name=EventNames.TASK_VERIFYING,
                    category=EventCategory.TASK,
                    source="harness",
                    task_id=task.id,
                    execution_id=execution.id,
                    agent_id=agent.id,
                    correlation_id=task.id,
                )
            )

            # ----------------------------------------------------------
            # Version 1 verification
            #
            # For now, a successful model response is considered valid.
            #
            # Real verification will be added later.
            # ----------------------------------------------------------

            task.complete(result)

            # ==========================================================
            # Agent Finished
            # ==========================================================

            agent.finish()

            self.events.publish(
                create_event(
                    name=EventNames.AGENT_COMPLETED,
                    category=EventCategory.AGENT,
                    source="harness",
                    task_id=task.id,
                    execution_id=execution.id,
                    agent_id=agent.id,
                    correlation_id=task.id,
                )
            )

            # ==========================================================
            # Task Completed
            # ==========================================================

            self.events.publish(
                create_event(
                    name=EventNames.TASK_COMPLETED,
                    category=EventCategory.TASK,
                    source="harness",
                    task_id=task.id,
                    execution_id=execution.id,
                    agent_id=agent.id,
                    correlation_id=task.id,
                    data={
                        "title": task.title,
                    },
                )
            )

            return HarnessResult(
                success=True,
                task=task,
                execution=execution,
                response=response,
            )

        except Exception as exc:

            error_message = str(exc)

            # ----------------------------------------------------------
            # Attempt to recover Agent state.
            # ----------------------------------------------------------

            try:
                if (
                    agent_name is not None
                    or task.assigned_agent is not None
                ):
                    agent = self.select_agent(
                        task,
                        agent_name=agent_name,
                    )

                    agent.mark_error()

                    self.events.publish(
                        create_event(
                            name=EventNames.AGENT_FAILED,
                            category=EventCategory.AGENT,
                            source="harness",
                            task_id=task.id,
                            execution_id=(
                                execution.id
                                if execution
                                else None
                            ),
                            agent_id=agent.id,
                            correlation_id=task.id,
                            severity=EventSeverity.ERROR,
                            data={
                                "error": error_message,
                            },
                        )
                    )
            except Exception:
                # Do not mask the original failure.
                pass

            # ----------------------------------------------------------
            # Fail Execution
            # ----------------------------------------------------------

            if execution is not None:
                try:
                    if execution.status.value == "running":
                        execution.fail(error_message)
                except Exception:
                    pass

            # ----------------------------------------------------------
            # Fail Task
            # ----------------------------------------------------------

            try:
                if not task.is_terminal():
                    task.fail(
                        error_message,
                        retry=False,
                    )
            except Exception:
                pass

            # ----------------------------------------------------------
            # Emit Task Failure
            # ----------------------------------------------------------

            self.events.publish(
                create_event(
                    name=EventNames.TASK_FAILED,
                    category=EventCategory.TASK,
                    source="harness",
                    task_id=task.id,
                    execution_id=(
                        execution.id
                        if execution
                        else None
                    ),
                    correlation_id=task.id,
                    severity=EventSeverity.ERROR,
                    data={
                        "error": error_message,
                    },
                )
            )

            return HarnessResult(
                success=False,
                task=task,
                execution=execution,
                response=response,
                error=error_message,
            )

    # ---------------------------------------------------------------------
    # Utilities
    # ---------------------------------------------------------------------

    @staticmethod
    def _format_inputs(
        inputs: Dict[str, Any],
    ) -> str:
        """
        Convert Task input data into a simple prompt representation.

        This is intentionally basic.

        Structured prompt construction will become its own service later.
        """

        lines: List[str] = []

        for key, value in inputs.items():
            lines.append(
                f"- {key}: {value}"
            )

        return "\n".join(lines)


# ============================================================================
# DEVELOPMENT TEST
# ============================================================================


def run_tool_tests() -> None:
    """Verify the Harness owns tool execution-mode decisions."""
    harness = AgentHarness()

    assert isinstance(harness.memory, MemoryStore)
    assert isinstance(harness.voice, VoiceService)
    assert callable(harness.record_voice)
    assert callable(harness.transcribe_voice)
    assert callable(harness.get_memory)
    assert callable(harness.save_memory)
    assert callable(harness.compact_memory)

    assert harness.tool_execution_mode("web_search") == "direct"
    assert harness.tool_execution_mode("get_current_time") == "direct"
    assert harness.tool_execution_mode("get_system_metrics") == "direct"

    assert harness.tool_execution_mode("search_vault") == "synthesize"
    assert harness.tool_execution_mode("read_obsidian_note") == "synthesize"
    assert harness.tool_execution_mode("get_daily_vault_summary") == "direct"
    assert harness.tools.require("get_daily_vault_summary").handler.__self__ is harness
    assert harness.tools.require("get_daily_vault_summary").handler.__func__ is AgentHarness.execute_daily_vault_summary

    # Wave-2 privileged tools must be registered centrally.
    for name in {
        "launch_app",
        "write_obsidian_note",
        "run_terminal_command",
        "launch_swarm",
    }:
        tool = harness.tools.get(name)
        assert tool is not None
        assert tool.risk.value == "privileged"
        assert tool.local_access is True
        assert tool.mutates_state is True

    # Do not execute real Wave-2 side effects during the core contract test.
    # the legacy runtime into the core test. We only verify routing ownership.

    print("✓ Harness tool-routing contract passed")


def run_policy_tests() -> None:
    """Verify that Harness Tool execution is gated by PolicyEngine."""
    harness = AgentHarness()

    task = Task(
        title="Policy harness test",
        description="Test policy-protected Tool execution.",
        workspace="development",
        metadata={"agent": "Researcher"},
    )
    agent = harness.select_agent(task)

    # Researcher is explicitly permitted to use web_search.
    result = harness._authorize_tool(
        "web_search",
        task=task,
        agent=agent,
        source="harness.test",
    )
    assert result.decision == PolicyDecision.ALLOW

    # ------------------------------------------------------------------
    # Wave 2: privileged tools
    #
    # The UI/local interface is trusted and therefore auto-approved after
    # all normal Policy DENY checks pass. Discord is intentionally NOT a
    # trusted source and must stop at APPROVAL_REQUIRED.
    # ------------------------------------------------------------------
    trusted_local = Task(
        title="Trusted local Wave-2 policy test",
        description="Test source-aware approval for privileged tools.",
        workspace="system",
        metadata={"agent": "Coordinator"},
    )
    coordinator = harness.select_agent(trusted_local)

    privileged_tools = {
        "launch_app",
        "write_obsidian_note",
        "run_terminal_command",
        "launch_swarm",
    }

    for tool_name in privileged_tools:
        tool = harness.tools.get(tool_name)
        assert tool is not None, f"Missing Wave-2 Tool: {tool_name}"
        assert tool.risk.value == "privileged"
        assert tool.local_access is True
        assert tool.mutates_state is True

        local_result = harness._authorize_tool(
            tool_name,
            task=trusted_local,
            agent=coordinator,
            source="ui",
        )
        assert local_result.decision == PolicyDecision.ALLOW
        assert local_result.metadata.get("source_auto_approved") is True

        discord_result = harness._authorize_tool(
            tool_name,
            task=trusted_local,
            agent=coordinator,
            source="discord",
        )
        assert discord_result.approval_required, (
            f"Policy bypass: Discord auto-approved {tool_name}"
        )

        approved_result = harness._authorize_tool(
            tool_name,
            task=trusted_local,
            agent=coordinator,
            source="discord",
            user_approved=True,
        )
        assert approved_result.decision == PolicyDecision.ALLOW

    print("✓ Wave-2 privileged tools auto-approve from UI")
    print("✓ Wave-2 privileged tools require approval from Discord")

    # An unapproved Tool must not be authorized.
    # The Coordinator is intentionally tested against a Tool it is not
    # permitted to use. We only exercise the authorization boundary here;
    # no real Tool handler is executed.
    blocked = Task(
        title="Policy denial test",
        description="Test denied Tool authorization.",
        workspace="development",
        metadata={"agent": "Coordinator"},
    )
    blocked_coordinator = harness.select_agent(blocked)

    denied_tool = harness.tools.get("web_search")
    assert denied_tool is not None, "Missing web_search Tool for policy test"

    # Coordinator is allowed to use the safe Wave-1 tools in normal runtime,
    # so web_search is no longer a valid denial probe. Temporarily use a
    # synthetic Tool that is absent from the Coordinator's permission set.
    from .tools import Tool, ToolRisk

    synthetic_denied_tool = Tool(
        name="policy_denied_test",
        description="Synthetic Tool used only to verify Policy denial.",
        handler=lambda: (_ for _ in ()).throw(
            AssertionError("Denied Tool handler was executed.")
        ),
        risk=ToolRisk.SAFE,
    )
    harness.tools.register(synthetic_denied_tool)

    try:
        harness._authorize_tool(
            "policy_denied_test",
            task=blocked,
            agent=blocked_coordinator,
            source="harness.test",
        )
    except PermissionError:
        pass
    else:
        raise AssertionError("Policy bypass: denied Tool authorized")

    print("✓ Harness Policy boundary passed")


def run_tests() -> None:
    """
    End-to-end Harness test.

    This test DOES communicate with the locally installed Ollama provider.

    It intentionally uses a tiny prompt so that we can prove the complete
    architecture without involving the existing bot.py.
    """

    run_tool_tests()
    run_policy_tests()

    print("=" * 60)
    print("ARNIE AGENT HARNESS TEST")
    print("=" * 60)

    # ------------------------------------------------------------------
    # Capture Events
    # ------------------------------------------------------------------

    captured_events: List[Event] = []

    event_bus = EventBus()

    event_bus.subscribe(
        lambda event: captured_events.append(event)
    )

    # ------------------------------------------------------------------
    # Create Harness
    # ------------------------------------------------------------------

    harness = AgentHarness(
        event_bus=event_bus,
    )

    print("\nProviders:")
    for provider in harness.models.list_providers():
        print(f"  ✓ {provider}")

    print("\nAgents:")

    for agent in harness.agents.list_agents():
        print(
            f"  ✓ {agent.name} "
            f"({agent.model_capability()})"
        )

    # ------------------------------------------------------------------
    # Create Task
    # ------------------------------------------------------------------

    task = Task(
        title="Harness smoke test",
        description=(
            "Explain what a GPU is in one short sentence."
        ),
        workspace="development",
        metadata={
            "agent_capability": "reasoning",
        },
    )

    print("\nTask:")
    print(f"  ID: {task.id}")
    print(f"  Title: {task.title}")

    # ------------------------------------------------------------------
    # Run Task
    # ------------------------------------------------------------------

    print("\nRunning Harness...")

    result = harness.run(task)

    # ------------------------------------------------------------------
    # Result
    # ------------------------------------------------------------------

    if not result.success:
        print()
        print("HARNESS TEST FAILED")
        print(f"Error: {result.error}")
        raise SystemExit(1)

    print("\nModel response:")
    print("-" * 60)

    if result.response:
        print(result.response.content)

    print("-" * 60)

    # ------------------------------------------------------------------
    # Validate Task
    # ------------------------------------------------------------------

    assert result.success is True
    assert result.task.status == TaskStatus.COMPLETED
    assert result.execution is not None
    assert result.execution.status.value == "completed"
    assert result.response is not None
    assert result.response.content.strip()

    print("\nTask:")
    print(f"  Status: {result.task.status.value}")

    print("\nExecution:")
    print(f"  Status: {result.execution.status.value}")
    print(f"  Agent:  {result.execution.agent_id}")
    print(f"  Model:  {result.execution.model}")
    print(f"  Provider: {result.execution.provider}")

    # ------------------------------------------------------------------
    # Validate Events
    # ------------------------------------------------------------------

    print("\nEvents:")

    for event in captured_events:
        print(
            f"  ✓ {event.name}"
        )

    required_events = {
        EventNames.TASK_QUEUED,
        EventNames.TASK_ASSIGNED,
        EventNames.AGENT_STARTED,
        EventNames.TASK_STARTED,
        EventNames.MODEL_REQUESTED,
        EventNames.MODEL_COMPLETED,
        EventNames.TASK_VERIFYING,
        EventNames.AGENT_COMPLETED,
        EventNames.TASK_COMPLETED,
    }

    captured_names = {
        event.name
        for event in captured_events
    }

    missing = required_events - captured_names

    assert not missing, (
        "Missing expected events: "
        + ", ".join(sorted(missing))
    )

    # ------------------------------------------------------------------
    # Final
    # ------------------------------------------------------------------

    print()
    print("=" * 60)
    print("AGENT HARNESS TEST PASSED")
    print("=" * 60)


if __name__ == "__main__":
    run_tests()
