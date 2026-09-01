"""ARNIE AgenticOS HTTP interface adapter.

FastAPI routes live here so bot.py remains the Discord interface adapter.
This module owns HTTP transport and request/response translation only; actual
work remains owned by AgenticOS Runtime, Harness, capabilities, and scheduler.
"""

import asyncio
import json
import os
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.agent_runtime import AgentRuntime
from core.harness import AgentHarness
from capabilities.voice.http import VoiceHTTPAdapter
from capabilities.audit.service import (
    create_session as audit_create_session,
    get_session as audit_get_session,
    save_processes as audit_save_processes,
    complete_session as audit_complete_session,
    list_sessions as audit_list_sessions,
    mark_report_generated as audit_mark_report,
)
from capabilities.audit.report import generate_report as audit_generate_report

from capabilities.time_savings.service import (
    log_entry as ts_log_entry,
    list_entries as ts_list_entries,
    total_hours as ts_total_hours,
    summary as ts_summary,
)

from capabilities.prospects import load_prospects

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



class AuditCreatePayload(BaseModel):
    firm_name: str
    prospect_id: str = ""
    client_id: str = ""
    auditor: str = "Kane"


class AuditCompletePayload(BaseModel):
    processes: list
    staff_rates: dict = {}
    notes: str = ""
    staff_count: int = 0
    client_count: int = 0
    practice_tier: str = ""

class TimeSavingPayload(BaseModel):
    hours: float
    description: str
    category: str = "other"
    logged_by: str = "Kane"


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

    assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "assets")
    os.makedirs(assets_dir, exist_ok=True)
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

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

    @app.post("/api/chat/reset")
    async def api_chat_reset():
        """Clear web chat history so the updated system prompt takes effect."""
        import sqlite3, traceback, os
        try:
            db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "memory.db")
            with sqlite3.connect(db_path) as con:
                con.execute("DELETE FROM messages WHERE channel_id=?", (web_channel_id,))
                con.execute("DELETE FROM channel_summaries WHERE channel_id=?", (web_channel_id,))
            return JSONResponse(content={"status": "ok", "message": "Chat history cleared."})
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e), "trace": traceback.format_exc()})

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

        return FileResponse(index_path, headers={"Cache-Control": "no-store, no-cache, must-revalidate"})



    @app.get("/api/prospects")
    async def get_prospects(status: str | None = None):
        from dataclasses import asdict
        STRIP = {"notes", "raw_research"}
        slim = [
            {k: v for k, v in asdict(p).items() if k not in STRIP}
            for p in load_prospects()
        ]
        if status:
            slim = [p for p in slim if p.get("status") == status]
        return JSONResponse(content={"prospects": slim})

    @app.get("/api/prospects/{prospect_id}")
    async def get_prospect(prospect_id: str):
        from dataclasses import asdict
        for p in load_prospects():
            if p.id == prospect_id:
                return JSONResponse(content={"prospect": asdict(p)})
        return JSONResponse(status_code=404, content={"error": "Prospect not found."})

    @app.get("/api/discovery/queue")
    async def get_discovery_queue():
        from core.db import get_db
        db = get_db()
        try:
            counts = {
                row["status"]: row["n"]
                for row in db.execute(
                    "SELECT status, COUNT(*) AS n FROM discovery_queue GROUP BY status"
                ).fetchall()
            }
            total = sum(counts.values())
            next_rows = db.execute(
                "SELECT town, county FROM discovery_queue "
                "WHERE status='pending' ORDER BY id LIMIT 5"
            ).fetchall()
        finally:
            db.close()

        return JSONResponse(content={
            "total": total,
            "pending": counts.get("pending", 0),
            "running": counts.get("running", 0),
            "done": counts.get("done", 0),
            "failed": counts.get("failed", 0),
            "next": [{"town": r["town"], "county": r["county"]} for r in next_rows],
        })

    # ── Audit routes ─────────────────────────────────────────────────────────

    @app.post("/api/audit/session")
    async def api_audit_create(payload: AuditCreatePayload):
        from dataclasses import asdict
        session = audit_create_session(
            firm_name=payload.firm_name,
            auditor=payload.auditor,
            prospect_id=payload.prospect_id,
            client_id=payload.client_id,
        )
        return JSONResponse(content={"session": asdict(session)})

    @app.get("/api/audit/sessions")
    async def api_audit_list(status: str | None = None):
        from dataclasses import asdict
        sessions = audit_list_sessions(status=status)
        return JSONResponse(content={"sessions": [asdict(s) for s in sessions]})

    @app.get("/api/audit/session/{session_id}")
    async def api_audit_get(session_id: str):
        from dataclasses import asdict
        session = audit_get_session(session_id)
        if session is None:
            return JSONResponse(status_code=404, content={"error": "Audit session not found."})
        return JSONResponse(content={"session": asdict(session)})

    @app.post("/api/audit/{session_id}/complete")
    async def api_audit_complete(session_id: str, payload: AuditCompletePayload):
        from dataclasses import asdict
        updated = audit_save_processes(
            session_id,
            payload.processes,
            staff_rates=payload.staff_rates or None,
        )
        if updated is None:
            return JSONResponse(status_code=404, content={"error": "Audit session not found."})
        completed = audit_complete_session(
            session_id,
            notes=payload.notes,
            staff_count=payload.staff_count,
            client_count=payload.client_count,
            practice_tier=payload.practice_tier,
        )
        return JSONResponse(content={"session": asdict(completed)})


    @app.get("/api/audit/report/{session_id}")
    async def api_audit_report(session_id: str):
        from capabilities.audit.scoring import score_processes
        from fastapi.responses import HTMLResponse
        session = audit_get_session(session_id)
        if session is None:
            return JSONResponse(status_code=404, content={"error": "Audit session not found."})
        scores = score_processes(session.processes or [])
        report_path = audit_generate_report(session, scores)
        audit_mark_report(session_id, str(report_path))
        return HTMLResponse(content=report_path.read_text(encoding="utf-8"))

    @app.get("/prospect/{prospect_id}", response_class=FileResponse)
    async def prospect_profile(prospect_id: str):
        p = os.path.join(os.path.dirname(__file__), "web", "prospect.html")
        if not os.path.exists(p):
            return JSONResponse(status_code=404, content={"error": "web/prospect.html missing."})
        return FileResponse(p)

    @app.get("/prospects", response_class=FileResponse)
    async def prospect_pool():
        p = os.path.join(os.path.dirname(__file__), "web", "prospects.html")
        if not os.path.exists(p):
            return JSONResponse(status_code=404, content={"error": "web/prospects.html missing."})
        return FileResponse(p, headers={"Cache-Control": "no-store, no-cache, must-revalidate"})

    @app.get("/audit", response_class=FileResponse)
    async def audit_interface():
        audit_path = os.path.join(os.path.dirname(__file__), "web", "audit.html")
        if not os.path.exists(audit_path):
            return JSONResponse(status_code=404, content={"error": "web/audit.html missing."})
        return FileResponse(audit_path, headers={"Cache-Control": "no-store, no-cache, must-revalidate"})


    # ── Internal time savings ────────────────────────────────────────────────

    @app.get("/api/savings")
    async def api_savings_summary():
        """Merged time savings: auto-logged (SQLite) + manual (JSON)."""
        from core.db import get_activity_summary
        try:
            auto = get_activity_summary()
        except Exception:
            auto = {"total_hours": 0, "breakdown": []}
        # Manual entries from existing JSON service
        try:
            manual_hours = ts_summary().get("total_hours", 0)
        except Exception:
            manual_hours = 0
        total_hours = auto["total_hours"] + manual_hours
        return JSONResponse(content={
            "total_hours": round(total_hours, 1),
            "auto_hours": auto["total_hours"],
            "manual_hours": round(manual_hours, 1),
            "breakdown": auto["breakdown"],
        })

    @app.get("/api/internal/time-savings")
    async def api_time_savings_list():
        from dataclasses import asdict
        return JSONResponse(content={
            "summary": ts_summary(),
            "entries": [asdict(e) for e in ts_list_entries()],
        })

    @app.post("/api/internal/time-savings")
    async def api_time_savings_log(payload: TimeSavingPayload):
        from dataclasses import asdict
        entry = ts_log_entry(
            hours=payload.hours,
            description=payload.description,
            category=payload.category,
            logged_by=payload.logged_by,
        )
        return JSONResponse(content={"entry": asdict(entry), "total_hours": ts_total_hours()})

    return app
