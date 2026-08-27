"""Local application-launch capability for AgenticOS.

This module owns the actual OS-level application launch operation.
Authorization belongs to the AgenticOS PolicyEngine/ToolRegistry boundary.
"""

from __future__ import annotations

import os
import subprocess
from typing import Dict


APP_SHORTCUT_MAP: Dict[str, str] = {
    "obsidian": r"C:\Users\%USERNAME%\AppData\Local\Programs\obsidian\Obsidian.exe",
    "vscode": r"C:\Users\%USERNAME%\AppData\Local\Programs\Microsoft VS Code\Code.exe",
    "code": r"C:\Users\%USERNAME%\AppData\Local\Programs\Microsoft VS Code\Code.exe",
    "terminal": "wt.exe",
    "cmd": "cmd.exe",
    "notepad": "notepad.exe",
    "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "explorer": "explorer.exe",
}


def launch_windows_app(app_name_or_path: str) -> str:
    """Launch a local Windows application.

    The caller is responsible for authorization/approval before invoking
    this capability.
    """
    target = str(app_name_or_path or "").strip()

    if not target:
        return "App Launcher Failure: No application target was supplied."

    clean_target = target.lower()
    resolved_path = APP_SHORTCUT_MAP.get(clean_target, target)
    resolved_path = os.path.expandvars(resolved_path)

    print(
        f"🚀 [System Capability] Launching application target: "
        f"{target}"
    )

    try:
        subprocess.Popen(
            resolved_path,
            shell=True,
            creationflags=(
                subprocess.DETACHED_PROCESS
                if os.name == "nt"
                else 0
            ),
        )

        return (
            f"SUCCESS! Launched application target: "
            f"'{clean_target}' (Path: {resolved_path})"
        )

    except Exception as exc:
        return (
            f"App Launcher Failure: Could not start "
            f"'{clean_target}'. Error: {exc}"
        )
