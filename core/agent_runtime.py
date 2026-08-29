"""ARNIE Agentic OS — Agent Runtime.

Owns conversational orchestration previously embedded in bot.py.
Interface adapters provide input/output; this module owns the decision and
execution flow between memory, intent routing, tools, policy, and model.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Awaitable, Callable, Dict, Optional

from .config import (
    AGENT_ROUTING_ENABLED,
    MEMORY_INJECTION_ENABLED,
    MEMORY_INJECTION_MIN_SCORE,
    MEMORY_INJECTION_TOP_K,
    MEMORY_PER_TURN_ENABLED,
    MEMORY_PER_TURN_MIN_SCORE,
    MEMORY_PER_TURN_TOP_K,
)
from .harness import AgentHarness
from .tasks import Task
from .tools import ToolRegistry, ToolRisk
from .intent import IntentRouter

log = logging.getLogger(__name__)


class ToolApprovalRequired(Exception):
    """Raised when a request needs human approval before Tool execution."""

    def __init__(self, tool_name: str, arguments: dict, message: str):
        super().__init__(message)
        self.tool_name = tool_name
        self.arguments = dict(arguments or {})
        self.message = message


class AgentRuntime:
    """AgenticOS conversational runtime used by all interface adapters."""

    def __init__(
        self,
        *,
        harness: AgentHarness,
        tool_registry: ToolRegistry,
        intent_router: IntentRouter,
        base_system_prompt: str,
        owner_extensions: str,
        model: str = "hermes3:8b",
    ) -> None:
        self.harness = harness
        self.tools = tool_registry
        self.intent_router = intent_router
        self.base_system_prompt = base_system_prompt
        self.owner_extensions = owner_extensions
        self.model = model

    async def execute_intent_tool(
        self,
        tool_name: str,
        arguments: dict,
        *,
        source: str,
        user_approved: bool = False,
    ) -> Any:
        """Execute a registered Tool through the canonical Harness/Policy boundary."""
        tool = self.tools.require(tool_name)

        workspace = (
            "system"
            if tool.risk == ToolRisk.PRIVILEGED
            else "personal"
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

        agent = self.harness.select_agent(task)
        policy_result = self.harness._authorize_tool(
            tool_name,
            task=task,
            agent=agent,
            source=source,
            user_approved=user_approved,
        )

        if policy_result.approval_required:
            raise ToolApprovalRequired(
                tool_name,
                arguments,
                policy_result.message,
            )

        return await self.harness.execute_tool_async(
            tool_name,
            arguments,
            task=task,
            agent=agent,
            source=source,
            user_approved=user_approved,
        )

    async def execute(
        self,
        channel_id: str,
        user_id: str,
        clean_content: str,
        is_owner: bool,
        source: str = "ui",
    ) -> str:
        """Run the complete conversational AgenticOS execution path."""
        history = self.harness.get_memory(channel_id)

        # --- PHASE 17: MEMORY INJECTION ---
        memory_context = ""
        if MEMORY_INJECTION_ENABLED:
            try:
                from capabilities.vault import retrieve_relevant
                snippets = retrieve_relevant(
                    query=clean_content,
                    top_k=MEMORY_INJECTION_TOP_K,
                    min_score=MEMORY_INJECTION_MIN_SCORE,
                )
                if snippets:
                    memory_context = "\n\n[MEMORY CONTEXT — what you already know about the user and their world]\n"
                    memory_context += "\n".join(f"• {s[:400]}" for s in snippets)
                    memory_context += "\n[END MEMORY CONTEXT]"
            except Exception as _mem_err:
                pass  # memory injection is best-effort; never block the response

        # --- PHASE 18: AGENT ROUTING ---
        # execute() is the conversational entrypoint and has no Task of its
        # own (Tasks are created per-tool-call in execute_intent_tool), so
        # there is no workspace to inspect yet — ordinary chat is treated
        # as the "personal" workspace.
        _task_workspace = "personal"
        agent_prefix = ""
        _model = self.model
        if AGENT_ROUTING_ENABLED:
            try:
                from core.model_router import get_model_for_workspace
                _agent_prompt = self.harness.agents.get_system_prompt_for_workspace(
                    _task_workspace
                )
                if _agent_prompt:
                    agent_prefix = _agent_prompt + "\n\n"
                _model, _provider = get_model_for_workspace(_task_workspace)
            except Exception as _routing_err:
                log.warning(f"Agent routing failed (best-effort): {_routing_err}")

        _is_first_turn = not history

        if _is_first_turn:
            full_prompt = agent_prefix + self.base_system_prompt + (
                self.owner_extensions if is_owner else ""
            ) + memory_context
            history.append({"role": "system", "content": full_prompt})

        # --- PHASE 23: PER-TURN MEMORY INJECTION ---
        # Phase 17 already injected deep context into the system prompt on
        # turn one, so this compact inline prefix only fires on later turns
        # in the same conversation — otherwise ARNIE goes cold after the
        # first message. Best-effort: never blocks the response path.
        _user_message_text = clean_content
        if MEMORY_PER_TURN_ENABLED and not _is_first_turn:
            try:
                from capabilities.vault import retrieve_relevant
                _snippets = retrieve_relevant(
                    query=clean_content,
                    top_k=MEMORY_PER_TURN_TOP_K,
                    min_score=MEMORY_PER_TURN_MIN_SCORE,
                )
                if _snippets:
                    _mem_prefix = (
                        "[CONTEXT: "
                        + " | ".join(s[:200] for s in _snippets)
                        + "]\n\n"
                    )
                    _user_message_text = _mem_prefix + clean_content
            except Exception:
                pass  # memory injection is best-effort; never block the response

        self.harness.save_memory(channel_id, user_id, "user", clean_content)
        # Per-turn persona guardrail: prevent asterisk action narration
        _PERSONA_REMINDER = "[ABSOLUTE RULE: Do NOT write asterisks around anything. No *action*, no *voice*, no *laughs*. Zero asterisks. Speak directly.]\n"
        history.append({"role": "user", "content": _PERSONA_REMINDER + _user_message_text})

        swarm_match = re.match(
            r"^\s*(?:launch|run|deploy)\s+swarm:\s*(.+)$",
            clean_content,
            re.IGNORECASE,
        )

        # Metrics are now routed through the canonical AgenticOS intent/tool
        # boundary instead of a second implementation inside bot.py.
        intent = self.intent_router.route(
            clean_content,
            is_owner=is_owner,
        )

        print(
            f"🧭 [Intent Router] input={clean_content!r} "
            f"tool={intent.tool_name!r} args={intent.arguments!r}"
        )

        if is_owner and swarm_match:
            mission = swarm_match.group(1).strip()
            print(f"⚡ [Agent Action] Direct Swarm Intent Triggered: {mission}")
            tool_output = await self.execute_intent_tool(
                "launch_swarm",
                {"mission": mission},
                source=source,
            )
            bot_reply = str(tool_output)
            self.harness.save_memory(
                channel_id,
                user_id,
                "assistant",
                bot_reply,
            )
            return bot_reply

        direct_tool_name = intent.tool_name
        direct_tool_args = dict(intent.arguments)

        if direct_tool_name:
            print(
                f"🛠️ [Agent Action] Deterministic Wave-1 Tool: "
                f"{direct_tool_name}"
            )

            try:
                tool_output = await self.execute_intent_tool(
                    direct_tool_name,
                    direct_tool_args,
                    source=source,
                )

                if direct_tool_name == "get_daily_vault_summary":
                    bot_reply = str(tool_output)

                elif self.harness.tool_execution_mode(direct_tool_name) == "direct":
                    bot_reply = str(tool_output)

                else:
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
                        {"role": "system", "content": synthesis_prompt}
                    )

                    bot_reply = await self.harness.chat(
                        history,
                        model=self.model,
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

                self.harness.save_memory(
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
                    f"Get to the choppa — but that capability hit a wall: {err}"
                )
                self.harness.save_memory(
                    channel_id,
                    user_id,
                    "assistant",
                    bot_reply,
                )
                return bot_reply

        forced_command = False
        if is_owner and any(
            kw in clean_content.lower()
            for kw in ["terminal", "command"]
        ):
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
            elif (
                "dir" in clean_content.lower()
                or "files" in clean_content.lower()
            ):
                extracted_cmd = "dir"

            bot_reply = (
                f'<tool_call>{{"name": "run_terminal_command", '
                f'"arguments": {{"command": "{extracted_cmd}"}}}}</tool_call>'
            )
        else:
            bot_reply = await self.harness.chat(
                history,
                model=_model,
                capability="conversation",
            )

        has_tool = False
        tool_json_str = ""

        if is_owner:
            match = (
                re.search(
                    r"<tool_call>(.*?)</tool_call>",
                    bot_reply,
                    re.DOTALL,
                )
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

                if not self.tools.has(tool_name):
                    raise KeyError(f"Unknown Tool: {tool_name}")

                if tool_name == "search_vault":
                    args = dict(args)
                    args.setdefault("query", clean_content)

                tool_output = await self.execute_intent_tool(
                    tool_name,
                    args,
                    source=source,
                )

                if not forced_command:
                    self.harness.save_memory(
                        channel_id,
                        user_id,
                        "assistant",
                        bot_reply,
                    )
                    history.append(
                        {"role": "assistant", "content": bot_reply}
                    )

                tool_context = (
                    f"Tool output received:\n\n{tool_output}\n\n"
                    "Please generate your final response."
                )
                self.harness.save_memory(
                    channel_id,
                    user_id,
                    "system",
                    tool_context,
                )
                history.append(
                    {"role": "system", "content": tool_context}
                )

                bot_reply = await self.harness.chat(
                    history,
                    model=self.model,
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

        self.harness.save_memory(
            channel_id,
            user_id,
            "assistant",
            bot_reply,
        )
        return bot_reply


def create_agent_runtime(
    *,
    harness: AgentHarness,
    tool_registry: ToolRegistry,
    intent_router: IntentRouter,
    base_system_prompt: str,
    owner_extensions: str,
    model: str = "hermes3:8b",
) -> AgentRuntime:
    return AgentRuntime(
        harness=harness,
        tool_registry=tool_registry,
        intent_router=intent_router,
        base_system_prompt=base_system_prompt,
        owner_extensions=owner_extensions,
        model=model,
    )
