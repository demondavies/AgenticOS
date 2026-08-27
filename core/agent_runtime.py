"""Interface-independent AgenticOS chat and tool execution runtime."""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Awaitable, Callable

from .tasks import Task


class ToolApprovalRequired(Exception):
    """A request from an untrusted interface needs human approval."""

    def __init__(self, tool_name: str, arguments: dict, message: str):
        super().__init__(message)
        self.tool_name = tool_name
        self.arguments = dict(arguments or {})
        self.message = message


class AgentRuntime:
    """Own the legacy chat orchestration outside of a transport adapter."""

    def __init__(
        self,
        *,
        harness: Any,
        tool_registry: Any,
        intent_router: Any,
        model_chat: Callable[..., Awaitable[str]],
        metrics_provider: Callable[[], str],
        base_system_prompt: str,
        owner_extensions: str,
        privileged_risk: Any,
    ) -> None:
        self.harness = harness
        self.tool_registry = tool_registry
        self.intent_router = intent_router
        self.model_chat = model_chat
        self.metrics_provider = metrics_provider
        self.base_system_prompt = base_system_prompt
        self.owner_extensions = owner_extensions
        self.privileged_risk = privileged_risk

    async def execute_tool(
        self,
        tool_name: str,
        arguments: dict,
        *,
        source: str,
        user_approved: bool = False,
    ) -> Any:
        """Execute a registered tool through the Harness/Policy boundary."""
        tool = self.tool_registry.require(tool_name)
        workspace = (
            "system"
            if tool.risk == self.privileged_risk
            else "development"
        )
        task = Task(
            title=f"Tool request: {tool_name}",
            description=f"Execute AgenticOS Tool '{tool_name}'.",
            workspace=workspace,
            metadata={"source": source, "intent_routed": True},
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
        channel_id: str | int,
        user_id: str | int,
        clean_content: str,
        is_owner: bool,
        source: str = "ui",
    ) -> str:
        """Process one chat request without knowing its UI transport."""
        history = self.harness.get_memory(channel_id)
        if not history:
            prompt = self.base_system_prompt + (
                self.owner_extensions if is_owner else ""
            )
            history.append({"role": "system", "content": prompt})

        self.harness.save_memory(channel_id, user_id, "user", clean_content)
        history.append({"role": "user", "content": clean_content})

        swarm_match = re.match(
            r"^\s*(?:launch|run|deploy)\s+swarm:\s*(.+)$",
            clean_content,
            re.IGNORECASE,
        )
        metrics_keywords = [
            "cpu", "ram", "memory", "hardware", "system status",
            "telemetry", "metrics",
        ]
        if (
            is_owner
            and any(word in clean_content.lower() for word in metrics_keywords)
            and not clean_content.lower().startswith("launch swarm")
        ):
            try:
                telemetry = await asyncio.wait_for(
                    asyncio.to_thread(self.metrics_provider), timeout=5.0
                )
                reply = f"Here is your live system breakdown:\n\n{telemetry}"
            except asyncio.TimeoutError:
                reply = "I couldn't retrieve live system metrics within 5 seconds."
            except Exception as error:
                reply = f"I couldn't retrieve live system metrics: {error}"
            self.harness.save_memory(channel_id, user_id, "assistant", reply)
            return reply

        if is_owner and swarm_match:
            result = await self.execute_tool(
                "launch_swarm", {"mission": swarm_match.group(1).strip()}, source=source
            )
            reply = str(result)
            self.harness.save_memory(channel_id, user_id, "assistant", reply)
            return reply

        intent = self.intent_router.route(clean_content, is_owner=is_owner)
        direct_tool_name = intent.tool_name
        direct_tool_args = dict(intent.arguments)
        if direct_tool_name:
            try:
                result = await self.execute_tool(
                    direct_tool_name, direct_tool_args, source=source
                )
                if (
                    direct_tool_name == "get_daily_vault_summary"
                    or self.harness.tool_execution_mode(direct_tool_name) == "direct"
                ):
                    reply = str(result)
                else:
                    history.append({
                        "role": "system",
                        "content": self._synthesis_prompt(direct_tool_name, result),
                    })
                    reply = self._strip_tool_call(await self.model_chat(
                        history, model="hermes3:8b", capability="tool_synthesis"
                    ))
                    if not reply:
                        reply = str(result)
                self.harness.save_memory(channel_id, user_id, "assistant", reply)
                return reply
            except ToolApprovalRequired:
                raise
            except Exception as error:
                reply = f"I couldn't execute the {direct_tool_name} capability: {error}"
                self.harness.save_memory(channel_id, user_id, "assistant", reply)
                return reply

        forced_command = False
        if is_owner and any(word in clean_content.lower() for word in ["terminal", "command"]):
            forced_command = True
            command = "dir"
            if any(word in clean_content.lower() for word in ["ping", "internet", "connected"]):
                command = "ping google.com"
            elif any(word in clean_content.lower() for word in ["ipconfig", "network", "configuration"]):
                command = "ipconfig"
            reply = '<tool_call>{"name": "run_terminal_command", "arguments": {"command": "' + command + '"}}</tool_call>'
        else:
            reply = await self.model_chat(
                history, model="hermes3:8b", capability="conversation"
            )

        if is_owner:
            tool_match = self._tool_call_match(reply)
            if tool_match:
                try:
                    tool_data = json.loads(tool_match)
                    tool_name = tool_data.get("name")
                    arguments = tool_data.get("arguments", {}) or {}
                    if not isinstance(arguments, dict):
                        raise TypeError("Tool arguments must be a JSON object.")
                    if not self.tool_registry.has(tool_name):
                        raise KeyError(f"Unknown Tool: {tool_name}")
                    if tool_name == "search_vault":
                        arguments = dict(arguments)
                        arguments.setdefault("query", clean_content)
                    result = await self.execute_tool(tool_name, arguments, source=source)
                    if not forced_command:
                        self.harness.save_memory(channel_id, user_id, "assistant", reply)
                        history.append({"role": "assistant", "content": reply})
                    context = f"Tool output received:\n\n{result}\n\nPlease generate your final response."
                    self.harness.save_memory(channel_id, user_id, "system", context)
                    history.append({"role": "system", "content": context})
                    reply = await self.model_chat(
                        history, model="hermes3:8b", capability="conversation"
                    )
                except ToolApprovalRequired:
                    raise
                except Exception:
                    pass

        reply = self._strip_tool_call(reply)
        if not reply:
            reply = "🤖 Action completed successfully!"
        self.harness.save_memory(channel_id, user_id, "assistant", reply)
        return reply

    @staticmethod
    def _tool_call_match(reply: str) -> str | None:
        match = (
            re.search(r"<tool_call>(.*?)</tool_call>", reply, re.DOTALL)
            or re.search(
                r'(\{\s*"name"\s*:\s*".*?"\s*,\s*"arguments"\s*:\s*\{.*?\}\s*\})',
                reply,
                re.DOTALL,
            )
        )
        return match.group(1).strip() if match else None

    @staticmethod
    def _strip_tool_call(reply: str) -> str:
        reply = re.sub(r"<tool_call>.*?</tool_call>", "", reply, flags=re.DOTALL)
        return re.sub(
            r'\{\s*"name"\s*:\s*".*?"\s*,\s*"arguments"\s*:\s*\{.*?\}\s*\}',
            "",
            reply,
            flags=re.DOTALL,
        ).strip()

    @staticmethod
    def _synthesis_prompt(tool_name: str, result: Any) -> str:
        return (
            "TOOL RESULT — AUTHORITATIVE EVIDENCE\n"
            "====================================\n"
            f"Tool: {tool_name}\n\n{result}\n\n"
            "SYNTHESIS RULES:\n"
            "1. Answer the user's request using the tool result above.\n"
            "2. Treat the tool result as the current factual source.\n"
            "3. Do not claim you lack access to information that this tool has just retrieved.\n"
            "4. Do not replace retrieved facts with your training knowledge or knowledge cutoff.\n"
            "5. Do not invent facts, dates, versions, or sources.\n"
            "6. If the tool result is insufficient, say exactly what is missing rather than guessing.\n"
            "7. For web results, identify the relevant source/title when useful.\n"
        )
