"""
ARNIE Agentic OS
Agent Domain Model

This module defines the provider-independent Agent contract.

IMPORTANT:
- An Agent describes WHO performs work.
- A Task describes WHAT needs to be done.
- A Model provides the intelligence.
- Tools provide capabilities.
- The Harness eventually coordinates all of them.

This file deliberately does not import:
    Ollama
    SQLite
    FastAPI
    Discord
    ChromaDB
    Kokoro
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4


# ============================================================================
# HELPERS
# ============================================================================


def new_id(prefix: str) -> str:
    """Create a readable unique identifier."""
    return f"{prefix}_{uuid4().hex}"


# ============================================================================
# AGENT STATUS
# ============================================================================


class AgentStatus(str, Enum):
    """
    Current operational state of an Agent.
    """

    OFFLINE = "offline"
    IDLE = "idle"
    BUSY = "busy"
    PAUSED = "paused"
    ERROR = "error"


# ============================================================================
# AGENT CAPABILITY
# ============================================================================


@dataclass(frozen=True)
class AgentCapability:
    """
    Describes something an Agent is capable of doing.

    Examples:

        research
        coding
        reviewing
        summarization
        web_research
        file_analysis
        planning
    """

    name: str
    description: str = ""

    # Optional requirements that can later be used by the model router.
    required_capabilities: List[str] = field(default_factory=list)

    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# AGENT MODEL PROFILE
# ============================================================================


@dataclass
class AgentModelProfile:
    """
    Describes what kind of model an Agent prefers.

    The Agent does NOT directly select or instantiate a model provider.

    The model router will eventually resolve this profile.
    """

    capability: str = "conversation"

    preferred_model: Optional[str] = None

    fallback_models: List[str] = field(default_factory=list)

    # Whether this Agent requires local execution.
    local_only: bool = False

    # Whether the Agent can use remote providers.
    allow_remote: bool = True

    # Optional model requirements.
    requirements: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# AGENT EXECUTION POLICY
# ============================================================================


@dataclass
class AgentExecutionPolicy:
    """
    Defines operational limits for an Agent.
    """

    max_retries: int = 2

    timeout_seconds: Optional[int] = None

    # Whether the Agent is allowed to execute tools.
    allow_tools: bool = True

    # Whether human approval may be required before certain actions.
    require_approval_for_privileged_tools: bool = True

    # Maximum number of tool calls during one execution.
    max_tool_calls: int = 20

    # Arbitrary future policy settings.
    metadata: Dict[str, Any] = field(default_factory=dict)


# ============================================================================
# AGENT
# ============================================================================


@dataclass
class Agent:
    """
    The durable definition of an ARNIE Agent.

    An Agent represents a specialized worker.

    It defines:
        - identity
        - role
        - instructions
        - capabilities
        - model requirements
        - execution policy
        - available tools

    It does NOT execute model inference itself.

    The Harness will eventually take an Agent + Task and coordinate execution.
    """

    name: str

    role: str

    system_prompt: str

    id: str = field(default_factory=lambda: new_id("agent"))

    status: AgentStatus = AgentStatus.IDLE

    capabilities: List[AgentCapability] = field(default_factory=list)

    allowed_tools: List[str] = field(default_factory=list)

    model_profile: AgentModelProfile = field(
        default_factory=AgentModelProfile
    )

    execution_policy: AgentExecutionPolicy = field(
        default_factory=AgentExecutionPolicy
    )

    description: str = ""

    workspace: Optional[str] = None

    metadata: Dict[str, Any] = field(default_factory=dict)

    # ---------------------------------------------------------------------
    # Capability management
    # ---------------------------------------------------------------------

    def add_capability(
        self,
        capability: AgentCapability,
    ) -> None:
        """
        Add a capability if it does not already exist.
        """

        existing = {
            item.name.lower()
            for item in self.capabilities
        }

        if capability.name.lower() not in existing:
            self.capabilities.append(capability)

    def has_capability(
        self,
        capability_name: str,
    ) -> bool:
        """
        Check whether the Agent has a named capability.
        """

        target = capability_name.strip().lower()

        return any(
            capability.name.lower() == target
            for capability in self.capabilities
        )

    def capability_names(self) -> List[str]:
        """
        Return the Agent's capability names.
        """

        return [
            capability.name
            for capability in self.capabilities
        ]

    # ---------------------------------------------------------------------
    # Tool management
    # ---------------------------------------------------------------------

    def allow_tool(
        self,
        tool_name: str,
    ) -> None:
        """
        Grant this Agent access to a tool.
        """

        tool_name = tool_name.strip()

        if not tool_name:
            raise ValueError("Tool name cannot be empty.")

        if tool_name not in self.allowed_tools:
            self.allowed_tools.append(tool_name)

    def remove_tool(
        self,
        tool_name: str,
    ) -> None:
        """
        Remove a tool from the Agent's allowed tool list.
        """

        if tool_name in self.allowed_tools:
            self.allowed_tools.remove(tool_name)

    def can_use_tool(
        self,
        tool_name: str,
    ) -> bool:
        """
        Check whether the Agent is allowed to use a tool.
        """

        return tool_name in self.allowed_tools

    # ---------------------------------------------------------------------
    # Lifecycle
    # ---------------------------------------------------------------------

    def start(self) -> None:
        """
        Mark the Agent as busy.
        """

        if self.status == AgentStatus.PAUSED:
            raise ValueError(
                f"Agent '{self.name}' is paused."
            )

        if self.status == AgentStatus.ERROR:
            raise ValueError(
                f"Agent '{self.name}' is in an error state."
            )

        self.status = AgentStatus.BUSY

    def finish(self) -> None:
        """
        Return the Agent to an idle state.
        """

        self.status = AgentStatus.IDLE

    def pause(self) -> None:
        """
        Pause the Agent.
        """

        if self.status == AgentStatus.BUSY:
            raise ValueError(
                f"Agent '{self.name}' cannot be paused while busy."
            )

        self.status = AgentStatus.PAUSED

    def resume(self) -> None:
        """
        Resume a paused Agent.
        """

        if self.status != AgentStatus.PAUSED:
            raise ValueError(
                f"Agent '{self.name}' is not paused."
            )

        self.status = AgentStatus.IDLE

    def mark_error(self) -> None:
        """
        Mark the Agent as being in an error state.
        """

        self.status = AgentStatus.ERROR

    # ---------------------------------------------------------------------
    # Model requirements
    # ---------------------------------------------------------------------

    def requires_local_model(self) -> bool:
        """
        Return True if the Agent requires local inference.
        """

        return self.model_profile.local_only

    def preferred_model(self) -> Optional[str]:
        """
        Return an explicitly preferred model if configured.
        """

        return self.model_profile.preferred_model

    def model_capability(self) -> str:
        """
        Return the model capability requested by this Agent.
        """

        return self.model_profile.capability

    # ---------------------------------------------------------------------
    # Serialization
    # ---------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert the Agent to a JSON-friendly dictionary.
        """

        data = asdict(self)

        data["status"] = self.status.value

        return data


# ============================================================================
# WORKSPACE -> AGENT ROUTING
# ============================================================================


WORKSPACE_AGENT_NAMES: Dict[str, str] = {
    "agency": "Researcher",
    "swarm": "Coordinator",
    "development": "Forge",
    "media": "Coordinator",
    "personal": "Coordinator",
    "system": "Coordinator",
    "client": "Atlas",
    "prospects": "Scout",
    "outreach": "Pitch",
}


# ============================================================================
# AGENT REGISTRY
# ============================================================================


class AgentRegistry:
    """
    Registry of available Agents.

    The registry allows the Harness to discover and select Agents without
    hard-coding individual Agent classes throughout the application.
    """

    def __init__(self) -> None:
        self._agents: Dict[str, Agent] = {}

    def register(
        self,
        agent: Agent,
    ) -> None:
        """
        Register an Agent.
        """

        key = agent.id

        if key in self._agents:
            raise ValueError(
                f"Agent '{agent.id}' is already registered."
            )

        self._agents[key] = agent

    def get(
        self,
        agent_id: str,
    ) -> Agent:
        """
        Retrieve an Agent by ID.
        """

        if agent_id not in self._agents:
            raise KeyError(
                f"Agent '{agent_id}' is not registered."
            )

        return self._agents[agent_id]

    def find_by_name(
        self,
        name: str,
    ) -> Optional[Agent]:
        """
        Find an Agent by human-readable name.
        """

        target = name.strip().lower()

        for agent in self._agents.values():
            if agent.name.lower() == target:
                return agent

        return None

    def find_by_capability(
        self,
        capability: str,
    ) -> List[Agent]:
        """
        Return Agents capable of performing a given capability.
        """

        return [
            agent
            for agent in self._agents.values()
            if agent.has_capability(capability)
        ]

    def list_agents(self) -> List[Agent]:
        """
        Return all registered Agents.
        """

        return list(self._agents.values())

    def list_available_agents(self) -> List[Agent]:
        """
        Return Agents currently available for work.
        """

        return [
            agent
            for agent in self._agents.values()
            if agent.status == AgentStatus.IDLE
        ]

    def get_system_prompt_for_workspace(
        self,
        workspace: str,
    ) -> Optional[str]:
        """
        Return the best agent system prompt for this workspace type.
        """

        agent = self.find_by_workspace(workspace)

        if agent:
            return agent.system_prompt

        return None

    def find_by_workspace(
        self,
        workspace: str,
    ) -> Optional[Agent]:
        """
        Return the Agent responsible for a given workspace type, if any.
        """

        agent_name = WORKSPACE_AGENT_NAMES.get(workspace)

        if agent_name:
            return self.find_by_name(agent_name)

        return None


# ============================================================================
# BUILT-IN AGENT FACTORIES
# ============================================================================


def create_coordinator_agent() -> Agent:
    """
    Create ARNIE's initial Coordinator Agent.

    This is a definition only.

    It does NOT invoke Hermes.
    It does NOT call Ollama.
    """

    agent = Agent(
        name="Coordinator",
        role="Primary orchestration agent",
        description=(
            "Coordinates tasks, determines appropriate capabilities, "
            "and delegates work to specialist agents."
        ),
        system_prompt=(
            "You are the Coordinator for ARNIE Agentic OS. "
            "Your responsibility is to understand the user's objective, "
            "break complex work into appropriate tasks, and delegate "
            "specialized work when necessary."
        ),
        model_profile=AgentModelProfile(
            capability="reasoning",
            preferred_model="hermes3:8b",
            local_only=True,
        ),
    )

    agent.add_capability(
        AgentCapability(
            name="planning",
            description="Break complex objectives into actionable tasks.",
        )
    )

    agent.add_capability(
        AgentCapability(
            name="delegation",
            description="Delegate work to specialist agents.",
        )
    )

    # The Coordinator is the primary conversational/runtime Agent, so it
    # must be explicitly permitted to use the canonical safe Wave-1 tools.
    # PolicyEngine remains the authority for all authorization decisions.
    agent.allow_tool("get_current_time")
    agent.allow_tool("get_daily_vault_summary")
    agent.allow_tool("get_system_metrics")
    agent.allow_tool("read_obsidian_note")
    agent.allow_tool("search_vault")
    agent.allow_tool("web_search")
    agent.allow_tool("list_tasks")
    agent.allow_tool("get_task")

    # Privileged local capabilities are explicitly granted to the Coordinator.
    # The PolicyEngine remains responsible for workspace and approval gates.
    agent.allow_tool("launch_app")
    agent.allow_tool("write_obsidian_note")
    agent.allow_tool("run_terminal_command")
    agent.allow_tool("launch_swarm")

    # Agency workspace: the Coordinator launches Agency research missions
    # the same way it launches Swarm missions.
    agent.allow_tool("run_agency_research")

    return agent


def create_researcher_agent() -> Agent:
    """
    Create the initial Researcher Agent.
    """

    agent = Agent(
        name="Researcher",
        role="Research and information gathering specialist",
        description=(
            "Finds, evaluates and synthesizes information."
        ),
        system_prompt=(
            "You are ARNIE's Researcher. "
            "Gather relevant information, distinguish evidence from "
            "assumption, and produce clear research results."
        ),
        model_profile=AgentModelProfile(
            capability="research",
            preferred_model="hermes3:8b",
            local_only=True,
        ),
    )

    agent.add_capability(
        AgentCapability(
            name="research",
            description="Perform research and synthesize findings.",
        )
    )

    agent.add_capability(
        AgentCapability(
            name="web_research",
            description="Research information from permitted web sources.",
        )
    )

    agent.allow_tool("web_search")
    agent.allow_tool("get_current_time")

    return agent


def create_coder_agent() -> Agent:
    """
    Create the initial Coder Agent.

    The model preference is configuration and can be changed later without
    changing the Agent abstraction.
    """

    agent = Agent(
        name="Coder",
        role="Software development specialist",
        description=(
            "Designs, writes, modifies and reviews software."
        ),
        system_prompt=(
            "You are ARNIE's Coder. "
            "Write clear, maintainable code and explain important "
            "implementation decisions."
        ),
        model_profile=AgentModelProfile(
            capability="coding",
            preferred_model="qwen2.5-coder:7b",
            local_only=True,
        ),
        execution_policy=AgentExecutionPolicy(
            max_retries=2,
            max_tool_calls=20,
            require_approval_for_privileged_tools=True,
        ),
    )

    agent.add_capability(
        AgentCapability(
            name="coding",
            description="Write and modify software.",
        )
    )

    agent.add_capability(
        AgentCapability(
            name="debugging",
            description="Diagnose and fix software problems.",
        )
    )

    agent.add_capability(
        AgentCapability(
            name="code_review",
            description="Review code for correctness and quality.",
        )
    )

    agent.allow_tool("search_vault")
    agent.allow_tool("read_obsidian_note")
    agent.allow_tool("run_terminal_command")
    agent.allow_tool("write_obsidian_note")
    agent.allow_tool("launch_app")

    return agent


def create_reviewer_agent() -> Agent:
    """
    Create the initial Reviewer Agent.
    """

    agent = Agent(
        name="Reviewer",
        role="Verification and quality specialist",
        description=(
            "Reviews outputs and identifies correctness, quality and "
            "security problems."
        ),
        system_prompt=(
            "You are ARNIE's Reviewer. "
            "Critically inspect proposed outputs, identify problems, "
            "and clearly distinguish verified results from assumptions."
        ),
        model_profile=AgentModelProfile(
            capability="review",
            preferred_model="phi4-mini",
            local_only=True,
        ),
    )

    agent.add_capability(
        AgentCapability(
            name="review",
            description="Review work produced by other agents.",
        )
    )

    agent.add_capability(
        AgentCapability(
            name="verification",
            description="Verify whether a result satisfies its requirements.",
        )
    )

    return agent



def create_scout_agent() -> Agent:
    """
    Create the SCOUT Agent.

    SCOUT researches UK accountancy firms, builds structured Prospect
    records, and surfaces qualifying signals for PITCH.
    """

    agent = Agent(
        name="Scout",
        role="Lead research specialist",
        description=(
            "Researches UK accountancy practices, extracts software stack "
            "and pain signals, and populates the Prospect store for PITCH."
        ),
        system_prompt=(
            "You are Scout, the lead research agent for Kaizen Studios. "
            "Your job is to find and qualify UK independent accountancy "
            "practices (1-10 staff, £200k-£2m revenue) as potential Kaizen "
            "clients. Research each firm thoroughly: identify their software "
            "stack, surface inefficiency signals, and produce a clear, "
            "structured prospect record. Be precise and evidence-based."
        ),
        workspace="prospects",
        model_profile=AgentModelProfile(
            capability="research",
            preferred_model="hermes3:8b",
            local_only=True,
        ),
    )

    agent.add_capability(
        AgentCapability(
            name="research",
            description="Research accountancy firms and synthesise findings.",
        )
    )

    agent.add_capability(
        AgentCapability(
            name="web_research",
            description="Deep-research firms from permitted web sources.",
        )
    )

    agent.add_capability(
        AgentCapability(
            name="prospect_qualification",
            description="Qualify prospects against Kaizen Studios' ICP.",
        )
    )

    agent.allow_tool("web_search")
    agent.allow_tool("research_prospect")
    agent.allow_tool("list_prospects")
    agent.allow_tool("get_prospect")

    return agent


def create_pitch_agent() -> Agent:
    """
    Create the PITCH Agent.

    PITCH drafts personalised cold email and LinkedIn DM copy for each
    qualified prospect, drawing on Scout's research.
    """

    agent = Agent(
        name="Pitch",
        role="Outreach copywriting specialist",
        description=(
            "Generates personalised cold email and LinkedIn DM copy for "
            "qualified prospects, grounded in Scout's research."
        ),
        system_prompt=(
            "You are Pitch, the outreach copywriting agent for Kaizen Studios. "
            "Using research provided by Scout, you write concise, personalised "
            "cold emails (under 130 words) and LinkedIn DMs (under 90 words) "
            "for UK accountancy practice owners. Lead with their specific pain, "
            "reference concrete detail from their firm, and make one clear call "
            "to action: a free 30-minute discovery call. Never sound like a "
            "template. Never exaggerate. Be direct and professional."
        ),
        workspace="outreach",
        model_profile=AgentModelProfile(
            capability="synthesis",
            preferred_model="hermes3:8b",
            local_only=True,
        ),
    )

    agent.add_capability(
        AgentCapability(
            name="copywriting",
            description="Write personalised outreach copy.",
        )
    )

    agent.add_capability(
        AgentCapability(
            name="synthesis",
            description="Synthesise research into targeted messaging.",
        )
    )

    agent.allow_tool("get_prospect")
    agent.allow_tool("draft_outreach")

    return agent


def create_atlas_agent() -> Agent:
    """
    Create the ATLAS Agent.

    ATLAS handles client success: onboarding, savings baseline logging,
    monthly reporting, and retainer management.
    """

    agent = Agent(
        name="Atlas",
        role="Client success specialist",
        description=(
            "Manages the post-sale client relationship: onboarding, "
            "savings tracking, monthly reporting, and retainer billing."
        ),
        system_prompt=(
            "You are Atlas, the client success agent for Kaizen Studios. "
            "You manage every active client relationship after the Kaizen "
            "Audit is delivered. Your responsibilities are: onboarding new "
            "clients, logging before-state baselines (time per process, "
            "frequency, staff cost), tracking automation savings, generating "
            "monthly savings reports, and producing retainer invoices "
            "(20% of documented savings from Month 4 onward). "
            "Be methodical, transparent, and client-facing in tone."
        ),
        workspace="client",
        model_profile=AgentModelProfile(
            capability="reasoning",
            preferred_model="hermes3:8b",
            local_only=True,
        ),
    )

    agent.add_capability(
        AgentCapability(
            name="client_management",
            description="Manage active client accounts and relationships.",
        )
    )

    agent.add_capability(
        AgentCapability(
            name="reporting",
            description="Generate savings reports and retainer invoices.",
        )
    )

    agent.add_capability(
        AgentCapability(
            name="onboarding",
            description="Onboard new Kaizen Studios clients.",
        )
    )

    agent.allow_tool("get_client")
    agent.allow_tool("list_clients")
    agent.allow_tool("add_client")
    agent.allow_tool("update_client_status")
    agent.allow_tool("get_current_time")
    agent.allow_tool("log_savings_baseline")
    agent.allow_tool("list_savings_baselines")

    return agent


def create_forge_agent() -> Agent:
    """
    Create the FORGE Agent.

    FORGE builds and maintains automations: writing scripts, connecting
    APIs, and implementing the technical layer for each client workflow.
    """

    agent = Agent(
        name="Forge",
        role="Automation build specialist",
        description=(
            "Designs and builds client automations: scripts, API "
            "integrations, and workflow implementations."
        ),
        system_prompt=(
            "You are Forge, the automation build agent for Kaizen Studios. "
            "You implement the technical solutions identified during the "
            "Kaizen Audit. Write clean, maintainable Python. Prefer simple "
            "solutions over clever ones. Document what each automation does, "
            "what triggers it, and how to verify it ran correctly. "
            "Every automation you build should save the client measurable time."
        ),
        workspace="development",
        model_profile=AgentModelProfile(
            capability="coding",
            preferred_model="qwen2.5-coder:7b",
            local_only=True,
        ),
        execution_policy=AgentExecutionPolicy(
            max_retries=2,
            max_tool_calls=20,
            require_approval_for_privileged_tools=True,
        ),
    )

    agent.add_capability(
        AgentCapability(
            name="coding",
            description="Write and modify automation scripts.",
        )
    )

    agent.add_capability(
        AgentCapability(
            name="debugging",
            description="Diagnose and fix automation failures.",
        )
    )

    agent.add_capability(
        AgentCapability(
            name="api_integration",
            description="Connect external APIs and services.",
        )
    )

    agent.allow_tool("run_terminal_command")
    agent.allow_tool("search_vault")
    agent.allow_tool("read_obsidian_note")
    agent.allow_tool("write_obsidian_note")
    agent.allow_tool("launch_app")

    return agent


def create_default_agent_registry() -> AgentRegistry:
    """
    Create the initial built-in Agent registry.
    """

    registry = AgentRegistry()

    registry.register(create_coordinator_agent())
    registry.register(create_researcher_agent())
    registry.register(create_coder_agent())
    registry.register(create_reviewer_agent())

    # Kaizen Studios specialist agents
    registry.register(create_scout_agent())
    registry.register(create_pitch_agent())
    registry.register(create_atlas_agent())
    registry.register(create_forge_agent())

    return registry


# ============================================================================
# DEVELOPMENT TESTS
# ============================================================================


def run_tests() -> None:
    """
    Dependency-free tests for the Agent domain model.

    This test suite does NOT:
        - call Ollama
        - execute tools
        - access SQLite
        - access FastAPI
        - access Discord
        - access the existing ARNIE bot
    """

    print("=" * 60)
    print("ARNIE AGENT DOMAIN MODEL TEST")
    print("=" * 60)

    # ------------------------------------------------------------------
    # Test 1: Agent creation
    # ------------------------------------------------------------------

    agent = Agent(
        name="Test Agent",
        role="Test specialist",
        system_prompt="You are a test agent.",
    )

    assert agent.id.startswith("agent_")
    assert agent.status == AgentStatus.IDLE

    print("✓ Agent creation")

    # ------------------------------------------------------------------
    # Test 2: Capabilities
    # ------------------------------------------------------------------

    agent.add_capability(
        AgentCapability(
            name="testing",
            description="Can perform testing.",
        )
    )

    assert agent.has_capability("testing")
    assert "testing" in agent.capability_names()

    print("✓ Agent capabilities")

    # ------------------------------------------------------------------
    # Test 3: Duplicate capability protection
    # ------------------------------------------------------------------

    agent.add_capability(
        AgentCapability(
            name="testing",
            description="Duplicate capability.",
        )
    )

    assert len(agent.capabilities) == 1

    print("✓ Duplicate capability protection")

    # ------------------------------------------------------------------
    # Test 4: Tool permissions
    # ------------------------------------------------------------------

    agent.allow_tool("test_tool")

    assert agent.can_use_tool("test_tool")

    agent.remove_tool("test_tool")

    assert not agent.can_use_tool("test_tool")

    print("✓ Tool permissions")

    # ------------------------------------------------------------------
    # Test 5: Agent lifecycle
    # ------------------------------------------------------------------

    agent.start()

    assert agent.status == AgentStatus.BUSY

    agent.finish()

    assert agent.status == AgentStatus.IDLE

    print("✓ Agent lifecycle")

    # ------------------------------------------------------------------
    # Test 6: Pause / resume
    # ------------------------------------------------------------------

    agent.pause()

    assert agent.status == AgentStatus.PAUSED

    agent.resume()

    assert agent.status == AgentStatus.IDLE

    print("✓ Pause / resume")

    # ------------------------------------------------------------------
    # Test 7: Model profile
    # ------------------------------------------------------------------

    coding_agent = Agent(
        name="Coding Test",
        role="Coding specialist",
        system_prompt="You write code.",
        model_profile=AgentModelProfile(
            capability="coding",
            preferred_model="test-model",
            local_only=True,
        ),
    )

    assert coding_agent.model_capability() == "coding"
    assert coding_agent.preferred_model() == "test-model"
    assert coding_agent.requires_local_model() is True

    print("✓ Model profile")

    # ------------------------------------------------------------------
    # Test 8: Registry
    # ------------------------------------------------------------------

    registry = AgentRegistry()

    registry.register(agent)

    found = registry.get(agent.id)

    assert found is agent

    print("✓ Agent registry")

    # ------------------------------------------------------------------
    # Test 9: Capability lookup
    # ------------------------------------------------------------------

    researcher = create_researcher_agent()

    registry.register(researcher)

    matches = registry.find_by_capability("research")

    assert researcher in matches

    print("✓ Capability lookup")

    # ------------------------------------------------------------------
    # Test 10: Built-in agents
    # ------------------------------------------------------------------

    default_registry = create_default_agent_registry()

    agents = default_registry.list_agents()

    assert len(agents) == 8

    names = {
        item.name
        for item in agents
    }

    assert "Coordinator" in names
    assert "Researcher" in names
    assert "Coder" in names
    assert "Reviewer" in names
    assert "Scout" in names
    assert "Pitch" in names
    assert "Atlas" in names
    assert "Forge" in names

    coordinator = default_registry.find_by_name("Coordinator")
    assert coordinator is not None

    for tool_name in {
        "launch_app",
        "write_obsidian_note",
        "run_terminal_command",
        "launch_swarm",
    }:
        assert coordinator.can_use_tool(tool_name)

    assert researcher.can_use_tool("web_search")
    assert researcher.can_use_tool("get_current_time")
    assert not researcher.can_use_tool("launch_app")

    coder = default_registry.find_by_name("Coder")
    assert coder is not None
    assert coder.can_use_tool("search_vault")
    assert coder.can_use_tool("read_obsidian_note")
    assert coder.can_use_tool("run_terminal_command")
    assert coder.can_use_tool("write_obsidian_note")
    assert coder.can_use_tool("launch_app")
    assert not coder.can_use_tool("launch_swarm")

    reviewer = default_registry.find_by_name("Reviewer")
    assert reviewer is not None
    assert not reviewer.can_use_tool("launch_app")
    assert not reviewer.can_use_tool("run_terminal_command")

    print("✓ Default Agent registry")
    print("✓ Coordinator Wave-2 privileged permissions")
    print("✓ Coder Wave-2 local permissions")
    print("✓ Researcher/Reviewer privilege isolation")

    # ------------------------------------------------------------------
    # Test 11: Serialization
    # ------------------------------------------------------------------

    data = researcher.to_dict()

    assert isinstance(data, dict)
    assert data["name"] == "Researcher"
    assert data["status"] == "idle"

    print("✓ Agent serialization")

    print()
    print("=" * 60)
    print("AGENT DOMAIN MODEL TEST PASSED")
    print("=" * 60)


if __name__ == "__main__":
    run_tests()