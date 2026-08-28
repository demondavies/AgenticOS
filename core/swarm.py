"""
ARNIE Agentic OS
Multi-agent swarm orchestration capability.

Owns the Researcher -> Coder -> Reviewer -> Sandbox pipeline and staged
artifact state. Interface adapters should call SwarmManager rather than
implementing swarm orchestration themselves.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import uuid

from typing import Awaitable, Callable, Dict, Any


STAGED_ARTIFACTS: Dict[str, Dict[str, Any]] = {}


class SubAgent:
    def __init__(
        self,
        name: str,
        system_prompt: str,
        model_name: str = "hermes3:8b",
        model_chat: Callable[..., Awaitable[str]] | None = None,
    ):
        self.name = name
        self.system_prompt = system_prompt
        self.model_name = model_name
        self.model_chat = model_chat

    async def run_task(self, task_description: str) -> str:
        if self.model_chat is None:
            raise RuntimeError("Swarm SubAgent requires a model_chat callback.")

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": task_description},
        ]

        capability = (
            "research"
            if self.name.lower() == "researcher"
            else "coding"
            if self.name.lower() == "coder"
            else "reasoning"
        )

        return await self.model_chat(
            messages,
            model=self.model_name,
            capability=capability,
        )


class SwarmManager:
    def __init__(
        self,
        model_chat: Callable[..., Awaitable[str]],
        research_web: Callable[..., Awaitable[str]] | None = None,
        max_retries: int = 3,
        sandbox_dir: str = r"G:\AgenticOS\data",
    ):
        self.model_chat = model_chat
        self.research_web = research_web
        self.max_retries = max_retries
        self.sandbox_dir = sandbox_dir
        self.agents = {
            "researcher": SubAgent(
                "Researcher",
                "You are a Lead Technical Researcher. Synthesize web documentation, code specs, and API structures into clean architecture plans.",
                model_name="hermes3:8b",
                model_chat=model_chat,
            ),
            "coder": SubAgent(
                "Coder",
                "You are an expert developer. Produce clean, complete, working Python/JS code block based on research specifications. Do NOT include conversation.",
                model_name="qwen2.5-coder:7b",
                model_chat=model_chat,
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
                model_name="phi4-mini",
                model_chat=model_chat,
            ),
        }

    async def _research_web(self, query: str, crawl_top_n: int = 2) -> str:
        """Delegate web research to the injected web capability."""
        if self.research_web is None:
            raise RuntimeError("SwarmManager requires a research_web capability.")
        return await self.research_web(query, crawl_top_n=crawl_top_n)

    async def _audit_code(self, code_content: str) -> dict:
        review_raw = await self.agents["reviewer"].run_task(
            f"Review this code:\n\n{code_content}"
        )
        clean_json = re.sub(r"```(?:json)?", "", review_raw).strip("` \n")

        try:
            return json.loads(clean_json)
        except Exception:
            passed = (
                "passed: true" in review_raw.lower()
                or "no issues" in review_raw.lower()
            )
            return {
                "passed": passed,
                "issues": ["Could not parse structured JSON review format."],
                "feedback": review_raw,
            }

    async def _test_code_in_sandbox(self, code_content: str) -> dict:
        if (
            "def " not in code_content
            and "import " not in code_content
            and "print(" not in code_content
        ):
            return {
                "executed": False,
                "passed": True,
                "output": "Non-executable script or documentation block.",
            }

        clean_code = re.sub(
            r"```(?:python)?",
            "",
            code_content,
        ).strip("` \n")

        os.makedirs(self.sandbox_dir, exist_ok=True)
        temp_file_path = os.path.join(
            self.sandbox_dir,
            f"sandbox_{uuid.uuid4().hex[:8]}.py",
        )

        try:
            with open(temp_file_path, "w", encoding="utf-8") as temp_file:
                temp_file.write(clean_code)

            result = await asyncio.to_thread(
                subprocess.run,
                [sys.executable, temp_file_path],
                capture_output=True,
                text=True,
                timeout=5,
                cwd=self.sandbox_dir,
            )

            stdout = result.stdout.strip()
            stderr = result.stderr.strip()

            if result.returncode == 0:
                return {
                    "executed": True,
                    "passed": True,
                    "output": stdout or "Executed with 0 errors (No print output).",
                }

            return {
                "executed": True,
                "passed": False,
                "output": (
                    f"RUNTIME EXCEPTION (Exit Code {result.returncode}):\n"
                    f"{stderr}"
                ),
            }

        except subprocess.TimeoutExpired:
            return {
                "executed": True,
                "passed": False,
                "output": "RUNTIME TIMEOUT EXCEPTION: Code execution exceeded 5-second limit.",
            }
        except Exception as exc:
            return {
                "executed": True,
                "passed": False,
                "output": f"SANDBOX FAILURE: {str(exc)}",
            }
        finally:
            if os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except OSError:
                    pass

    async def execute_crew_pipeline(self, mission_prompt: str) -> dict:
        print(
            f"\n🚀 [Swarm Engine] Deep Mission Initiated: '{mission_prompt}'"
        )

        raw_web_data = await self._research_web(mission_prompt, crawl_top_n=2)

        researcher_input = (
            f"USER MISSION: {mission_prompt}\n\n"
            f"LIVE DEEP WEB SCRAPE DATA:\n{raw_web_data}\n\n"
            "Task: Synthesize technical specifications and clean code "
            "architecture based on the live web data above."
        )

        research_out = await self.agents["researcher"].run_task(
            researcher_input
        )

        current_code = ""
        last_feedback = ""
        attempt_logs = []
        is_approved = False

        for attempt in range(1, self.max_retries + 1):
            print(
                f"💻 [Swarm] Phase 2 (Attempt {attempt}/{self.max_retries}): "
                "Generating Code..."
            )

            if attempt == 1:
                coder_prompt = (
                    f"Mission: {mission_prompt}\n"
                    f"Architectural Specs:\n{research_out}"
                )
            else:
                coder_prompt = (
                    f"Mission: {mission_prompt}\n\n"
                    "YOUR PREVIOUS CODE FAILED TESTING. FIX THESE BUGS IMMEDIATELY:\n"
                    f"{last_feedback}\n\n"
                    f"Previous Code:\n{current_code}"
                )

            current_code = await self.agents["coder"].run_task(coder_prompt)

            print("🧐 [Swarm] Phase 3A: Reviewer Static Audit...")
            audit_result = await self._audit_code(current_code)

            if not audit_result.get("passed", False):
                last_feedback = (
                    "STATIC AUDIT FAILURE:\n"
                    f"{audit_result.get('feedback')}"
                )
                attempt_logs.append({
                    "attempt": attempt,
                    "stage": "Audit",
                    "passed": False,
                    "feedback": last_feedback,
                })
                print(f"⚠️ Static Audit Failed on attempt {attempt}")
                continue

            print("🧪 [Swarm] Phase 3B: Running Subprocess Sandbox Test...")
            sandbox_result = await self._test_code_in_sandbox(current_code)

            if not sandbox_result.get("passed", False):
                last_feedback = (
                    "SANDBOX EXECUTION FAILURE:\n"
                    f"{sandbox_result.get('output')}"
                )
                attempt_logs.append({
                    "attempt": attempt,
                    "stage": "Sandbox",
                    "passed": False,
                    "feedback": last_feedback,
                })
                print(f"❌ Sandbox Execution Failed on attempt {attempt}")
                continue

            print(
                f"✅ [Swarm] AUDIT & SANDBOX EXECUTION PASSED ON ATTEMPT {attempt}!"
            )
            is_approved = True
            attempt_logs.append({
                "attempt": attempt,
                "stage": "Sandbox",
                "passed": True,
                "feedback": sandbox_result.get("output"),
            })
            break

        task_id = str(uuid.uuid4())
        safe_mission_name = re.sub(
            r"[^a-zA-Z0-9]",
            "_",
            mission_prompt[:20],
        ).strip("_")
        default_filename = f"Swarm_{safe_mission_name}.md"

        audit_history_md = ""
        for log in attempt_logs:
            status_icon = "✅ PASSED" if log["passed"] else "❌ FAILED"
            audit_history_md += (
                f"- **Pass {log['attempt']} ({log['stage']})**: "
                f"{status_icon}\n  *Log*: {log['feedback']}\n\n"
            )

        full_content = (
            f"# SWARM MISSION: {mission_prompt}\n\n"
            f"**SANDBOX TEST STATUS:** "
            f"{'PASSED' if is_approved else 'STAGED WITH ERRORS'}\n"
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
            "is_approved": is_approved,
        }

        return {
            "task_id": task_id,
            "default_filename": default_filename,
            "is_approved": is_approved,
            "code": current_code,
            "full_content": full_content,
        }


def validate_dependencies() -> None:
    """Validate SwarmManager's injected capability contract."""

    async def _model_chat(*args: Any, **kwargs: Any) -> str:
        return ""

    async def _research_web(*args: Any, **kwargs: Any) -> str:
        return ""

    manager = SwarmManager(
        model_chat=_model_chat,
        research_web=_research_web,
    )

    assert manager.model_chat is _model_chat
    assert manager.research_web is _research_web
    assert manager.max_retries == 3


if __name__ == "__main__":
    validate_dependencies()
    print("SWARM DEPENDENCY TEST PASSED")
