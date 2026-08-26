"""AgenticOS hardware/system telemetry capability."""

from __future__ import annotations

import os
from datetime import datetime

import psutil


def get_system_metrics() -> str:
    """Return current CPU, RAM, disk, process, and local time telemetry."""
    print("⚡ [System] Pulling hardware system metrics telemetry...")

    try:
        cpu_load = psutil.cpu_percent(interval=0.3)
        cpu_count = psutil.cpu_count(logical=True)
        ram = psutil.virtual_memory()

        drive_letter = "G:\\" if os.path.exists("G:\\") else "C:\\"
        disk = psutil.disk_usage(drive_letter)

        ram_used_gb = ram.used / (1024 ** 3)
        ram_total_gb = ram.total / (1024 ** 3)
        disk_free_gb = disk.free / (1024 ** 3)
        disk_total_gb = disk.total / (1024 ** 3)
        process_count = len(psutil.pids())

        return (
            "**ARNIE HARDWARE TELEMETRY REPORT**\n\n"
            f"⚡ **CPU Load:** `{cpu_load}%` ({cpu_count} Logical Cores)\n"
            f"🧠 **RAM Utilization:** `{ram.percent}%` "
            f"({ram_used_gb:.1f} GB / {ram_total_gb:.1f} GB)\n"
            f"💾 **Drive Space ({drive_letter}):** `{disk.percent}% Used` "
            f"({disk_free_gb:.1f} GB free of {disk_total_gb:.1f} GB)\n"
            f"⚙️ **Active OS Processes:** `{process_count}`\n"
            f"⏱️ **System Time:** "
            f"`{datetime.now().strftime('%H:%M:%S')}`"
        )

    except Exception as exc:
        return (
            "Telemetry Error: Unable to fetch kernel metrics: "
            f"{exc}"
        )
