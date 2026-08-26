# ARNIE — Agentic OS Architecture

> Status: Architecture Draft
> Version: 1.0
> Purpose: Define the architectural direction of ARNIE before major refactoring.
>
> This document is the source of truth for the ARNIE architecture.
> Code should evolve toward this document rather than the document being rewritten
> to justify accidental implementation decisions.

---

# 1. VISION

ARNIE is a local-first Agentic Operating System.

The purpose of ARNIE is not simply to provide a chatbot interface.

ARNIE is intended to become a persistent personal AI operating environment capable of:

- conversation
- memory
- knowledge retrieval
- reasoning
- research
- tool execution
- task execution
- multi-agent collaboration
- code generation
- verification
- voice interaction
- scheduled autonomous work
- workspace-specific workflows
- human approval
- future migration from local hardware to remote infrastructure

The central architectural principle is:

> ARNIE should be an orchestration layer independent of any single model,
> interface, provider, or hardware configuration.

---

# 2. CORE PRINCIPLES

## 2.1 Local First

The system should work primarily on local infrastructure.

Local execution is preferred for:

- private memory
- personal knowledge
- local files
- system control
- voice
- development
- model inference where practical

Remote infrastructure may be introduced when useful.

Examples:

- VPS execution
- remote model providers
- hosted APIs
- external services
- remote workers

Remote infrastructure must remain a provider rather than becoming the definition
of ARNIE itself.

---

## 2.2 Provider Independence

ARNIE must not be architecturally dependent on Ollama.

Ollama is currently the primary local model runtime.

Future runtimes may include:

- Ollama
- OpenAI-compatible APIs
- remote inference servers
- cloud model APIs
- local alternative runtimes
- specialized coding models
- specialized reasoning models

The application layer should request model capabilities rather than directly
depending on a specific runtime.

Bad:

    ollama.chat(model="hermes3:8b")

Preferred architectural direction:

    model_provider.chat(request)

---

## 2.3 Model Specialization

There is no requirement for one model to perform every task.

Different models may be selected according to capability.

Examples:

- general conversation
- reasoning
- coding
- research synthesis
- classification
- summarization
- reviewing
- embeddings
- speech recognition
- speech synthesis

Model selection belongs to the model/provider layer and orchestration system,
not individual application features.

---

## 2.4 Persistent State

Important system state must survive process restarts.

The system must not rely on Python process memory for important durable state.

Current staged swarm artifacts are held in:

    STAGED_ARTIFACTS = {}

This is acceptable as a prototype but is not sufficient for the final architecture.

Future durable state should include:

- tasks
- task status
- agent runs
- artifacts
- approvals
- execution history
- schedules
- memory metadata
- workflow state

---

## 2.5 Human Control

ARNIE may be autonomous without becoming uncontrolled.

Actions with meaningful consequences should support:

- staging
- verification
- approval
- rejection
- audit history

The existing swarm approval model is a foundation for this principle.

---

## 2.6 Observable Execution

ARNIE should be able to explain:

- what it is doing
- which task is running
- which agent is responsible
- which tools were used
- what failed
- what succeeded
- what is waiting for approval
- what remains queued

The system should eventually expose this through an event stream.

---

# 3. CURRENT SYSTEM

The current implementation is concentrated primarily in:

    bot.py

The existing backend contains:

- SQLite conversation memory
- Master Brain vault integration
- ChromaDB vector search
- Ollama embeddings
- local voice recording
- Faster-Whisper transcription
- Kokoro TTS
- The Oak voice configuration
- Playwright web scraping
- DuckDuckGo web search
- hardware telemetry
- terminal execution
- Windows application launching
- multi-agent swarm execution
- code review
- sandbox testing
- APScheduler jobs
- Discord integration
- FastAPI web infrastructure

The current dashboard is implemented in:

    index.html

The dashboard communicates with FastAPI endpoints.

---

# 4. CURRENT ARCHITECTURE

Current high-level structure:

    ┌─────────────────────────────────────────────┐
    │                  ARNIE                      │
    │                                             │
    │                  bot.py                     │
    │                                             │
    ├──────────────┬──────────────┬───────────────┤
    │              │              │               │
    │   Memory     │   Agents     │    Voice      │
    │              │              │               │
    │ SQLite       │ Swarm        │ Whisper       │
    │ ChromaDB     │ Researcher   │ Kokoro        │
    │ Master Brain │ Coder        │ The Oak       │
    │              │ Reviewer     │               │
    ├──────────────┴──────────────┴───────────────┤
    │                    Tools                    │
    │                                             │
    │ Web Search / Vault / Terminal / Apps /      │
    │ Metrics / Swarm / Time                      │
    ├─────────────────────────────────────────────┤
    │                  FastAPI                    │
    ├──────────────────────┬──────────────────────┤
    │                      │                      │
    │   Web Dashboard      │      Discord         │
    │                      │                      │
    └──────────────────────┴──────────────────────┘

This architecture works as a prototype.

It should not remain the final architecture.

---

# 5. TARGET ARCHITECTURE

The target architecture separates ARNIE into distinct layers.

    ┌────────────────────────────────────────────────────┐
    │                    INTERFACES                       │
    │                                                    │
    │ Web UI │ Voice │ Discord │ Future Interfaces       │
    └───────────────────────┬────────────────────────────┘
                            │
    ┌───────────────────────▼────────────────────────────┐
    │                  APPLICATION LAYER                  │
    │                                                    │
    │ Conversation │ Workspaces │ Commands │ Sessions    │
    └───────────────────────┬────────────────────────────┘
                            │
    ┌───────────────────────▼────────────────────────────┐
    │                  AGENT HARNESS                      │
    │                                                    │
    │ Tasks │ Agents │ Orchestration │ Policies          │
    │ Tool Execution │ Verification │ Events             │
    └─────────────┬──────────────┬──────────────┬────────┘
                  │              │              │
          ┌───────▼──────┐ ┌────▼───────┐ ┌────▼────────┐
          │    MEMORY    │ │   TOOLS    │ │   MODELS    │
          │              │ │            │ │             │
          │ Short Term   │ │ Web        │ │ Provider    │
          │ Long Term    │ │ Files      │ │ Selection   │
          │ Vector       │ │ Terminal   │ │ Routing     │
          │ Knowledge    │ │ Apps       │ │             │
          └───────┬──────┘ └────┬───────┘ └────┬────────┘
                  │              │              │
          ┌───────▼──────────────▼──────────────▼────────┐
          │                 INFRASTRUCTURE                │
          │                                               │
          │ SQLite │ ChromaDB │ Ollama │ Files │ OS       │
          │ Kokoro │ Whisper │ Scheduler │ Network        │
          └───────────────────────────────────────────────┘

---

# 6. CORE DOMAIN OBJECTS

The architecture is based around a small set of durable concepts.

Primary objects:

    Agent
    Task
    Tool
    Model
    Provider
    Memory
    Event
    Artifact
    Workspace
    Execution
    Approval

These objects should remain conceptually independent.

---

# 7. AGENT

An Agent is a specialized worker with:

- identity
- role
- instructions
- capabilities
- tool access
- model requirements
- execution policy

Conceptual structure:

    Agent
    ├── id
    ├── name
    ├── role
    ├── system_prompt
    ├── capabilities
    ├── allowed_tools
    ├── model_profile
    └── execution_policy

Examples:

    Coordinator
    Researcher
    Coder
    Reviewer
    Summarizer
    Voice Agent
    Prospecting Agent
    Media Agent

Agents should not directly own infrastructure.

An Agent should request capabilities from the harness.

---

# 8. TASK

A Task represents work ARNIE intends to perform.

Conceptual structure:

    Task
    ├── id
    ├── type
    ├── description
    ├── status
    ├── priority
    ├── creator
    ├── assigned_agent
    ├── workspace
    ├── inputs
    ├── outputs
    ├── parent_task
    ├── created_at
    ├── started_at
    ├── completed_at
    └── error

Tasks must be persistent.

---

# 9. TASK LIFECYCLE

Standard lifecycle:

    CREATED
       │
       ▼
    QUEUED
       │
       ▼
    ASSIGNED
       │
       ▼
    RUNNING
       │
       ├──────────────┐
       │              │
       ▼              ▼
    WAITING        FAILED
       │              │
       ▼              ▼
    RUNNING        RETRYING
       │              │
       └───────┬──────┘
               ▼
          VERIFYING
               │
          ┌────┴─────┐
          ▼          ▼
      COMPLETED   APPROVAL_REQUIRED
                         │
                    ┌────┴────┐
                    ▼         ▼
                APPROVED    REJECTED

Possible terminal states:

    COMPLETED
    FAILED
    CANCELLED
    REJECTED

---

# 10. EXECUTION

A Task may generate one or more Executions.

This is important because a task may be retried.

Example:

    Task: Build feature X

    Execution 1
        Agent: Coder
        Result: Failed

    Execution 2
        Agent: Coder
        Result: Passed

The Task remains the durable logical unit.

The Execution records what actually happened.

---

# 11. AGENT HARNESS

The Agent Harness is the central orchestration layer.

Its responsibility is to coordinate:

- tasks
- agents
- models
- tools
- memory
- verification
- approvals
- events

The harness should NOT itself become a giant collection of business logic.

Conceptual interface:

    harness.submit(task)

    harness.run(task)

    harness.assign(task, agent)

    harness.execute_tool(tool, input)

    harness.verify(result)

    harness.approve(task)

    harness.reject(task)

---

# 12. ORCHESTRATION

The existing SwarmManager is the prototype for orchestration.

Current swarm flow:

    Research
       ↓
    Code
       ↓
    Review
       ↓
    Sandbox
       ↓
    Retry if required
       ↓
    Stage Artifact
       ↓
    Human Approval

This pattern should be retained but generalized.

Future orchestration should support:

    Sequential workflows

    Parallel workflows

    Conditional workflows

    Retry workflows

    Human approval workflows

    Agent delegation

    Nested tasks

---

# 13. SWARM

Swarm is a workflow pattern, not the entire agent architecture.

A swarm consists of:

    Coordinator
        ↓
    Worker Agents
        ↓
    Verification
        ↓
    Result

Example:

    Researcher
        ↓
    Coder
        ↓
    Reviewer
        ↓
    Sandbox

The swarm should eventually use the same Task and Execution abstractions as
every other ARNIE workflow.

---

# 14. MODEL ABSTRACTION

ARNIE must separate model selection from model execution.

Target structure:

    ModelRequest
    ├── capability
    ├── task_type
    ├── context_requirement
    ├── reasoning_requirement
    ├── latency_requirement
    └── privacy_requirement

The model layer resolves the request.

Example:

    capability = "coding"

may resolve to:

    qwen2.5-coder:7b

while:

    capability = "conversation"

may resolve to:

    hermes3:8b

The exact model is configuration, not application architecture.

---

# 15. MODEL PROVIDERS

Target abstraction:

    ModelProvider
    ├── chat()
    ├── stream()
    ├── embed()
    └── health()

Possible implementations:

    OllamaProvider
    OpenAICompatibleProvider
    RemoteProvider
    FutureProvider

Application code should depend on ModelProvider interfaces rather than Ollama.

---

# 16. MEMORY

ARNIE has multiple memory layers.

## 16.1 Conversation Memory

Short-term conversational context.

Current implementation uses SQLite-backed message history.

Purpose:

- maintain recent conversation
- maintain session context
- support model prompts

---

## 16.2 Long-Term Memory

Persistent knowledge stored in the Master Brain.

Purpose:

- personal knowledge
- project knowledge
- decisions
- reference material
- durable context

---

## 16.3 Semantic Memory

ChromaDB provides vector retrieval.

Current implementation embeds Master Brain Markdown documents using:

    nomic-embed-text

The vector store should remain an implementation detail behind a memory interface.

---

## 16.4 Memory Interface

Target:

    memory.store()
    memory.retrieve()
    memory.search()
    memory.summarize()
    memory.compact()

The Agent should not need to know whether memory comes from:

    SQLite
    ChromaDB
    Markdown
    another vector database
    future remote storage

---

# 17. MASTER BRAIN

Master Brain is the persistent knowledge vault.

Current implementation:

    G:\Master_Brain

Markdown files are indexed into the vector store.

The architecture should preserve the principle:

    Human-readable source
            ↓
       Master Brain
            ↓
       Semantic Index

The Markdown vault remains the authoritative human-readable knowledge layer.

The vector database is an index.

The vector database should never become the only source of truth.

---

# 18. TOOLS

Tools are capabilities exposed to agents.

Current examples:

    web_search
    get_current_time
    write_obsidian_note
    read_obsidian_note
    search_vault
    run_terminal_command
    launch_swarm
    launch_app
    get_system_metrics

Tools should become explicit objects.

Conceptual structure:

    Tool
    ├── name
    ├── description
    ├── input_schema
    ├── permissions
    ├── execute()
    └── risk_level

---

# 19. TOOL SECURITY

Tools must eventually have permission levels.

Example:

    SAFE
        time
        read-only search

    CONTROLLED
        write files
        launch applications

    PRIVILEGED
        terminal commands
        system modifications

Agents should not automatically receive every tool.

Tool access should be capability-based.

---

# 20. TERMINAL EXECUTION

Terminal execution is currently available to the agent.

The current implementation blocks a small list of dangerous keywords.

This is not considered a sufficient long-term security boundary.

Future architecture should use:

    command policy
        ↓
    permission check
        ↓
    sandbox
        ↓
    execution
        ↓
    output capture
        ↓
    audit event

Potential future controls:

- allowlists
- command classification
- working-directory restrictions
- process isolation
- time limits
- resource limits
- human approval

---

# 21. ARTIFACTS

Agents frequently produce artifacts.

Examples:

    Markdown
    Python
    JavaScript
    reports
    research
    generated files
    code patches

Artifacts should have durable metadata.

Conceptual structure:

    Artifact
    ├── id
    ├── task_id
    ├── filename
    ├── path
    ├── type
    ├── status
    ├── created_at
    └── approved_at

---

# 22. STAGING

The current swarm uses a staging buffer before writing artifacts to Master Brain.

This principle should remain.

Preferred workflow:

    Generate
       ↓
    Validate
       ↓
    Stage
       ↓
    Human Review
       ↓
    Approve
       ↓
    Commit

This prevents agents from immediately making irreversible changes.

---

# 23. VERIFICATION

Agent output should not automatically be considered correct.

Verification may include:

    Static review
    Runtime testing
    Schema validation
    File validation
    Security review
    Human approval

The existing swarm reviewer and sandbox are early implementations of this idea.

---

# 24. EVENT SYSTEM

ARNIE should eventually expose a unified event stream.

Examples:

    task.created
    task.started
    task.completed
    task.failed

    agent.started
    agent.completed

    tool.called
    tool.completed
    tool.failed

    artifact.created
    artifact.staged
    artifact.approved

    memory.updated

    model.requested
    model.completed

The event system will eventually drive:

- dashboard updates
- logs
- debugging
- audit trails
- notifications
- autonomous monitoring

---

# 25. VOICE ARCHITECTURE

Voice is a subsystem rather than a special case of chat.

Current pipeline:

    Microphone
        ↓
    Local VAD Recorder
        ↓
    Faster-Whisper
        ↓
    ARNIE Agent Harness
        ↓
    Response
        ↓
    Speech Cleaner
        ↓
    Kokoro
        ↓
    The Oak

The existing voice implementation uses local recording and silence detection.

Speech transcription is performed locally.

Kokoro is kept resident in process memory.

The Oak voice is currently configured as:

    George 70%
    Onyx 30%

---

# 26. VOICE INTERFACE

The voice interface should eventually behave like any other interface.

It should submit:

    UserInput

to the same application/harness layer.

Voice should not create a separate intelligence system.

Preferred architecture:

    Voice Input
        ↓
    Speech-to-Text
        ↓
    User Message
        ↓
    Agent Harness
        ↓
    Response
        ↓
    Text-to-Speech

---

# 27. WEB INTERFACE

The current FastAPI dashboard is both:

- a user interface
- an engineering control panel

It currently provides access to:

- chat
- voice
- vault files
- note editing
- vector synchronization
- memory compaction
- cron jobs
- swarm approval

This interface should remain useful during development.

It should eventually evolve into the ARNIE control centre.

---

# 28. FUTURE UI

The eventual UI should expose the actual system concepts.

Primary areas:

    HOME
    BRAIN
    TASKS
    AGENCY
    MEDIA
    SYSTEM

---

## HOME

Purpose:

    What is ARNIE doing right now?

Potential information:

- active tasks
- current agents
- recent events
- alerts
- system health
- quick command interface

---

## BRAIN

Purpose:

    What does ARNIE know?

Potential information:

- Master Brain
- memories
- projects
- knowledge
- semantic search
- recent decisions

---

## TASKS

Purpose:

    What work is ARNIE performing?

Potential information:

- queue
- active tasks
- completed tasks
- failed tasks
- approvals
- execution history

---

## AGENCY

Purpose:

    Business operations.

Potential future capabilities:

- prospecting
- research
- client workflows
- delivery
- automation
- lead intelligence
- proposals
- reporting

Agency should be implemented as a workspace, not baked into the core harness.

---

## MEDIA

Purpose:

    Creative/media operations.

Potential future capabilities:

- music workflows
- YouTube workflows
- artwork
- metadata
- content production
- publishing pipelines

Media should also be implemented as a workspace.

---

## SYSTEM

Purpose:

    Infrastructure visibility.

Potential information:

- CPU
- RAM
- GPU
- disk
- model status
- provider status
- scheduler
- logs
- services

The existing telemetry tool is an early foundation.

---

# 29. WORKSPACES

A Workspace provides domain-specific context and tools.

Examples:

    Agency
    Media
    Development
    Personal

A workspace may define:

- memory scope
- tools
- agents
- workflows
- prompts
- files
- permissions

The core harness remains domain-neutral.

---

# 30. SCHEDULER

The current system uses APScheduler.

Existing scheduled work includes:

    Daily Master Brain summary
    Periodic memory compaction

Scheduler jobs should eventually create Tasks.

Preferred architecture:

    Scheduler
        ↓
    Create Task
        ↓
    Task Queue
        ↓
    Agent Harness

The scheduler should not directly implement business logic.

---

# 31. DISCORD

Discord is an interface.

It should not own the agent architecture.

Preferred flow:

    Discord Message
        ↓
    Application Input
        ↓
    Agent Harness
        ↓
    Response
        ↓
    Discord

The same task, memory and tool systems should work regardless of interface.

---

# 32. API LAYER

FastAPI provides the local HTTP interface.

The API layer should remain thin.

It should:

- validate requests
- authenticate requests
- invoke application services
- return results
- stream events

It should not contain core agent logic.

---

# 33. DATABASE STRATEGY

SQLite remains the default local transactional database.

Potential tables:

    tasks
    executions
    agents
    artifacts
    approvals
    events
    messages
    schedules
    workspaces

ChromaDB remains a semantic index rather than the transactional system.

---

# 34. FILE SYSTEM STRATEGY

Files should be treated as first-class artifacts.

Important distinction:

    Knowledge
        Master Brain

    Application state
        SQLite

    Semantic index
        ChromaDB

    Generated artifacts
        Workspace/file storage

    Temporary execution data
        data/

---

# 35. CONFIGURATION

Configuration should eventually be separated from implementation.

Potential configuration:

    config/
        models.yaml
        agents.yaml
        tools.yaml
        workspaces.yaml
        system.yaml

Secrets should never be stored directly in source code.

---

# 36. LOGGING

ARNIE should produce structured logs.

Minimum categories:

    SYSTEM
    MODEL
    AGENT
    TASK
    TOOL
    MEMORY
    VOICE
    WEB
    SECURITY

Future logs should support correlation IDs.

Example:

    Task ID
        ↓
    Agent Execution ID
        ↓
    Tool Call ID
        ↓
    Event ID

This makes debugging multi-agent workflows possible.

---

# 37. ERROR HANDLING

Errors should be explicit.

An error should identify:

- operation
- task
- agent
- provider
- tool
- reason
- retryability

Not every error should trigger a retry.

Categories:

    TRANSIENT
    PROVIDER_FAILURE
    VALIDATION_FAILURE
    SECURITY_FAILURE
    USER_REJECTION
    LOGIC_FAILURE
    RESOURCE_FAILURE

---

# 38. RETRIES

Retries should belong to the orchestration layer.

The system should avoid blindly retrying.

Retry policy should consider:

- error type
- attempt count
- cost
- task priority
- model availability
- whether the operation is idempotent

---

# 39. SECURITY MODEL

Security is a first-class architectural concern.

Principles:

1. Least privilege.
2. Explicit tool permissions.
3. Separate read and write capabilities.
4. Validate all external input.
5. Never trust model-generated tool calls.
6. Audit privileged actions.
7. Stage high-impact artifacts.
8. Prefer reversible operations.
9. Keep secrets outside prompts and source code.
10. Treat remote services as untrusted boundaries.

---

# 40. LOCAL → VPS MIGRATION

The architecture must support moving components without rewriting ARNIE.

Potential deployment:

    LOCAL ARNIE
        │
        ├── Local UI
        ├── Local SQLite
        ├── Local Master Brain
        ├── Local Ollama
        └── Local Voice

Later:

    ARNIE VPS
        │
        ├── API
        ├── Task Engine
        ├── SQLite/Postgres
        ├── Worker(s)
        └── Remote Model Provider

while local hardware may remain responsible for:

    Voice
    Desktop control
    Local files
    GPU inference

The harness should not care where execution occurs.

---

# 41. HARDWARE ABSTRACTION

Current system telemetry reads local CPU, RAM, disk and process information.

Future architecture should expose system capabilities through a Hardware/Runtime interface.

Potential capabilities:

    get_metrics()
    get_gpu_metrics()
    list_devices()
    health_check()

The rest of ARNIE should not directly depend on psutil.

---

# 42. DIRECTORY TARGET

The intended architecture is approximately:

    G:\AgenticOS\
    │
    ├── core\
    │   ├── harness.py
    │   ├── tasks.py
    │   ├── agents.py
    │   ├── models.py
    │   ├── tools.py
    │   ├── events.py
    │   └── config.py
    │
    ├── memory\
    │   ├── short_term.py
    │   ├── brain.py
    │   └── embeddings.py
    │
    ├── agents\
    │   ├── coordinator.py
    │   ├── researcher.py
    │   ├── coder.py
    │   └── reviewer.py
    │
    ├── providers\
    │   ├── ollama.py
    │   └── ...
    │
    ├── voice\
    │   ├── stt.py
    │   ├── tts.py
    │   └── speech_cleaner.py
    │
    ├── interfaces\
    │   ├── web.py
    │   └── discord.py
    │
    ├── workspaces\
    │   ├── agency\
    │   └── media\
    │
    ├── data\
    │
    ├── ui\
    │   └── index.html
    │
    └── ARCHITECTURE.md

This is the target, not an instruction to create every file immediately.

---

# 43. REFACTORING STRATEGY

The existing system should be refactored incrementally.

Do NOT perform a complete rewrite.

Each migration step must preserve a working system.

Preferred pattern:

    Existing implementation
            ↓
    Extract abstraction
            ↓
    Redirect existing code
            ↓
    Test
            ↓
    Remove duplication
            ↓
    Continue

---

# 44. PHASE 1 — ARCHITECTURAL FOUNDATION

Create the first core abstractions:

    Task
    Agent
    ModelProvider
    Tool
    Event

Do not immediately move every existing function.

The purpose is to establish stable contracts.

---

# 45. PHASE 2 — MODEL PROVIDER

Extract direct Ollama calls.

Current code directly invokes Ollama from multiple subsystems.

Replace those dependencies with:

    ModelProvider

Initial implementation:

    OllamaProvider

The behaviour should remain unchanged.

---

# 46. PHASE 3 — TASK ENGINE

Introduce persistent Tasks and Executions.

Migrate swarm missions first.

The existing swarm becomes the first real Task workflow.

---

# 47. PHASE 4 — AGENT EXTRACTION

Extract:

    Researcher
    Coder
    Reviewer

from the existing SubAgent/Swarm implementation.

They should become proper Agent definitions.

---

# 48. PHASE 5 — TOOL REGISTRY

Move tool functions into a registry.

Example:

    tool_registry.register(web_search)
    tool_registry.register(search_vault)
    tool_registry.register(run_terminal_command)

The model should receive only tools permitted by the current agent/task.

---

# 49. PHASE 6 — MEMORY INTERFACE

Wrap:

    SQLite
    Master Brain
    ChromaDB

behind memory services.

Do not replace the storage engines unnecessarily.

---

# 50. PHASE 7 — EVENT SYSTEM

Introduce event emission.

Initially events may simply be logged.

Later the dashboard can subscribe to them.

---

# 51. PHASE 8 — VOICE EXTRACTION

Move:

    recording
    transcription
    speech cleaning
    Kokoro

into the voice subsystem.

The intelligence remains in the central harness.

---

# 52. PHASE 9 — INTERFACE EXTRACTION

Move FastAPI and Discord into interface modules.

Both should call the same application/harness layer.

---

# 53. PHASE 10 — WORKSPACES

Introduce:

    Agency
    Media

as workspace-level systems.

The core remains domain-neutral.

---

# 54. PHASE 11 — UI EVOLUTION

Once the backend concepts are real, evolve the dashboard.

The UI should display:

    Tasks
    Agents
    Events
    Memory
    Workspaces
    System health

The UI should reflect the architecture rather than inventing its own state model.

---

# 55. TESTING STRATEGY

Every architectural extraction must preserve existing functionality.

Minimum test categories:

    Model provider tests
    Task lifecycle tests
    Tool permission tests
    Memory tests
    Agent tests
    Swarm tests
    Voice tests
    API tests

Critical tools should have explicit tests before being granted more autonomy.

---

# 56. DEVELOPMENT RULE

Never perform a large refactor without a working checkpoint.

Before major changes:

    git commit

After successful migration:

    git commit

Every architectural phase should be independently reversible.

---

# 57. ANTI-PATTERNS

Avoid:

## God Object

One class controlling:

- memory
- models
- tools
- voice
- UI
- scheduling
- agents

---

## Model Leakage

Application logic directly selecting:

    hermes3:8b

or:

    qwen2.5-coder:7b

where a capability abstraction should exist.

---

## Interface Leakage

Business logic directly depending on:

    FastAPI
    Discord
    browser JavaScript

---

## Infrastructure Leakage

Agents directly manipulating:

    SQLite
    ChromaDB
    filesystem
    subprocess

without going through appropriate services.

---

## In-Memory Critical State

Do not store important workflow state only in:

    dictionaries
    global variables
    process memory

---

## Autonomous Irreversible Actions

Do not allow model output to directly perform dangerous actions without policy,
validation and appropriate approval.

---

# 58. THE CENTRAL RULE

ARNIE is not:

    a chatbot with tools.

ARNIE is:

    a task-oriented orchestration system
    with conversational, memory, agent, tool and interface capabilities.

The chatbot is one interface.

The Agent Harness is the core.

---

# 59. SUCCESS CRITERIA

The architecture will be considered successful when:

1. The model runtime can be changed without rewriting agents.
2. The UI can be changed without rewriting agent logic.
3. Discord can be removed without affecting core functionality.
4. Voice can be disabled without affecting text operation.
5. A task survives an ARNIE restart.
6. Agents can be swapped or added independently.
7. Tools have explicit permissions.
8. Swarm workflows use the universal Task system.
9. Master Brain remains human-readable.
10. Local and remote model providers can coexist.
11. Agency and Media can evolve independently.
12. Execution history is observable.
13. Important actions are auditable.
14. The system can eventually move from local hardware to VPS infrastructure
    without architectural replacement.

---

# 60. IMMEDIATE NEXT STEP

Do NOT start by creating the entire target directory tree.

First create:

    core/
    core/models.py

and define the first stable domain contracts.

The first contracts should be:

    Task
    Agent
    ModelRequest
    ModelResponse
    ToolResult
    Event

Then implement:

    OllamaProvider

without changing ARNIE's observable behaviour.

This establishes the foundation for every subsequent refactor.

---

# END