"""ARNIE AgenticOS HTTP interface adapter.

FastAPI routes live here so bot.py remains the Discord interface adapter.
This module owns HTTP transport and request/response translation only; actual
work remains owned by AgenticOS Runtime, Harness, capabilities, and scheduler.
"""

import asyncio
import json
import os

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from core.agent_runtime import AgentRuntime
from core.harness import AgentHarness
from capabilities.voice.http import VoiceHTTPAdapter
from capabilities.vault import (
    get_vault_location,
    list_vault_notes,
    read_vault_file,
    save_vault_file,
    sync_master_brain_vector_db,
)


WEB_CHANNEL_ID = "local_web_dashboard"


class ChatPayload(BaseModel):
    message: str


class VoiceSpeakPayload(BaseModel):
    text: str


class GetNotePayload(BaseModel):
    filename: str


class SaveNotePayload(BaseModel):
    filename: str
    content: str


class ApprovalPayload(BaseModel):
    task_id: str
    target_filename: str | None = None


def create_app(
    *,
    agent_runtime: AgentRuntime,
    harness: AgentHarness,
    voice_api: VoiceHTTPAdapter,
    scheduler,
    web_channel_id: str = WEB_CHANNEL_ID,
) -> FastAPI:
    """Create the canonical ARNIE HTTP interface adapter."""
    app = FastAPI()

    @app.get("/api/vault/files")
    async def get_vault_files():
        return JSONResponse(
            content={
                "path": get_vault_location(),
                "files": list_vault_notes(),
            }
        )

    @app.post("/api/chat")
    async def api_chat(payload: ChatPayload):
        reply = await agent_runtime.execute(
            web_channel_id,
            "local_owner_web",
            payload.message,
            is_owner=True,
            source="ui",
        )

        latest_staged = harness.get_latest_staged_artifact()

        return JSONResponse(
            content={
                "reply": reply,
                "staged_artifact": latest_staged,
            }
        )

    @app.post("/api/voice/transcribe")
    async def api_voice_transcribe():
        return await voice_api.transcribe()

    @app.post("/api/voice/stream")
    async def api_voice_stream(payload: ChatPayload):
        return voice_api.stream_response(payload.message, is_owner=True)

    @app.post("/api/voice/listen")
    async def api_voice_listen():
        return await voice_api.listen()

    @app.post("/api/voice/speak")
    async def api_voice_speak(payload: VoiceSpeakPayload):
        return await voice_api.speak(payload.text)

    @app.get("/api/system/metrics")
    async def get_system_metrics():
        import psutil, os
        cpu = psutil.cpu_percent(interval=0.3)
        ram = psutil.virtual_memory()
        drive = "G:\\" if os.path.exists("G:\\") else "C:\\"
        disk = psutil.disk_usage(drive)
        return {
            "cpu_percent": cpu,
            "ram_percent": ram.percent,
            "ram_used_gb": round(ram.used / (1024**3), 1),
            "ram_total_gb": round(ram.total / (1024**3), 1),
            "disk_percent": disk.percent,
            "disk_free_gb": round(disk.free / (1024**3), 1),
        }

    @app.get("/api/tasks")
    async def get_tasks(status: str | None = None, workspace: str | None = None):
        tasks = harness.list_tasks(status=status, workspace=workspace)
        return JSONResponse(content={"tasks": tasks})

    @app.get("/api/tasks/{task_id}")
    async def get_task(task_id: str):
        task = harness.get_task(task_id)
        if task is None:
            return JSONResponse(
                status_code=404,
                content={"error": "Task not found."},
            )
        return JSONResponse(content={"task": task})

    @app.get("/api/events")
    async def stream_events():
        """Forward EventBus publications to the client as Server-Sent Events."""
        queue: asyncio.Queue = asyncio.Queue()

        subscription_id = harness.events.subscribe(
            lambda event: queue.put_nowait(event.to_dict())
        )

        async def event_stream():
            try:
                while True:
                    event = await queue.get()
                    yield f"data: {json.dumps(event)}\n\n"
            finally:
                harness.events.unsubscribe(subscription_id)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/cron/jobs")
    async def get_cron_jobs():
        jobs = []
        for job in scheduler.get_jobs():
            jobs.append(
                {
                    "id": job.id,
                    "next_run": str(job.next_run_time),
                    "trigger": str(job.trigger),
                }
            )
        return JSONResponse(content={"jobs": jobs})

    @app.post("/api/memory/compact")
    async def api_compact_memory():
        try:
            msg = await harness.compact_memory(web_channel_id, keep_recent=5)
            return JSONResponse(
                content={
                    "status": "success",
                    "message": msg,
                }
            )
        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"error": str(e)},
            )

    @app.post("/api/vector/sync")
    async def api_sync_vector_db():
        msg = sync_master_brain_vector_db()
        return JSONResponse(
            content={
                "status": "success",
                "message": msg,
            }
        )

    @app.get("/api/swarm/staged")
    async def get_staged_artifacts():
        return JSONResponse(content={"artifacts": harness.list_staged_artifacts()})

    @app.post("/api/swarm/approve")
    async def approve_staged_artifact(payload: ApprovalPayload):
        result = harness.approve_staged_artifact(
            payload.task_id,
            payload.target_filename,
        )
        if not result["ok"]:
            status_code = 404 if result["reason"] == "not_found" else 500
            return JSONResponse(
                status_code=status_code,
                content={"error": result["error"]},
            )

        print(f"💾 [Swarm Approval] Written to Master_Brain: {result['filename']}")
        return JSONResponse(
            content={
                "status": "success",
                "message": result["message"],
                "filename": result["filename"],
            }
        )

    @app.delete("/api/swarm/reject/{task_id}")
    async def reject_staged_artifact(task_id: str):
        if harness.reject_staged_artifact(task_id):
            return JSONResponse(
                content={
                    "status": "success",
                    "message": "Artifact discarded from staging memory!",
                }
            )
        return JSONResponse(
            status_code=404,
            content={"error": "Artifact ID missing."},
        )

    @app.post("/api/get_note")
    async def api_get_note(payload: GetNotePayload):
        try:
            result = read_vault_file(payload.filename)
            if result.startswith("Error: Note file ") and result.endswith(" missing."):
                return JSONResponse(
                    status_code=404,
                    content={"error": "File missing"},
                )
            if result.startswith("Error: Note filename is empty"):
                return JSONResponse(
                    status_code=400,
                    content={"error": result},
                )
            if result.startswith("Failed to read file:"):
                return JSONResponse(
                    status_code=500,
                    content={"error": result},
                )

            return JSONResponse(content={"content": result})

        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"error": str(e)},
            )

    @app.post("/api/save_note")
    async def api_save_note(payload: SaveNotePayload):
        try:
            result = save_vault_file(payload.filename, payload.content)
            if result.startswith("Failed to save file:"):
                return JSONResponse(
                    status_code=500,
                    content={"error": result},
                )

            return JSONResponse(
                content={
                    "status": "success",
                    "message": result,
                }
            )

        except Exception as e:
            return JSONResponse(
                status_code=500,
                content={"error": str(e)},
            )

    @app.get("/", response_class=FileResponse)
    async def dashboard():
        index_path = os.path.join(
            os.path.dirname(__file__),
            "web",
            "index.html",
        )

        if not os.path.exists(index_path):
            return JSONResponse(
                status_code=404,
                content={"error": "web/index.html file missing."},
            )

        return FileResponse(index_path)

    return app
