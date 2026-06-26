from __future__ import annotations
import asyncio
import json
import yaml
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .core import ollama, memory, context, evolution
from .core.manager import forge, debug_only, evolve
from .models.schemas import (
    ForgeRequest, DebugRequest, EvolutionRequest,
    ProjectMemoryResponse, StatusResponse
)

_cfg = yaml.safe_load(open(Path(__file__).parents[2] / "config.yaml"))
_EVO_CFG = _cfg.get("evolution", {})
_SERVER_CFG = _cfg.get("server", {})

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await memory.init_db()

    if _EVO_CFG.get("enabled", False):
        cron = _EVO_CFG.get("schedule_cron", "0 2 * * *")
        parts = cron.split()
        scheduler.add_job(
            _evolution_job,
            "cron",
            minute=parts[0], hour=parts[1],
            day=parts[2], month=parts[3], day_of_week=parts[4],
            id="evolution"
        )
        scheduler.start()

    yield
    scheduler.shutdown(wait=False)


async def _evolution_job():
    """Nightly evolution job — runs on all known projects."""
    async with await memory._db() as db:
        cur = await db.execute("SELECT path FROM projects")
        rows = await cur.fetchall()
    for row in rows:
        await evolution.run_evolution(row[0])


app = FastAPI(
    title="AutoForge AI",
    description="Autonomous local AI software engineer — multi-agent code generation",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ──────────────────────────────────────────────────────────────────

@app.get("/health", response_model=StatusResponse)
async def health():
    online = await ollama.is_online()
    models = await ollama.list_models() if online else []
    return StatusResponse(
        status="ok" if online else "ollama_offline",
        ollama_online=online,
        models=[m.get("name", "") for m in models],
    )


# ── Forge (main pipeline) ───────────────────────────────────────────────────

@app.post("/forge")
async def forge_project(request: ForgeRequest):
    """
    Main endpoint: triggers full multi-agent code generation pipeline.
    Returns Server-Sent Events stream.
    """
    async def stream():
        try:
            async for event in forge(request):
                yield event
        except Exception as e:
            err = json.dumps({"type": "forge_error", "agent": "orchestrator",
                              "message": str(e), "data": {}})
            yield f"data: {err}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


# ── Debug ───────────────────────────────────────────────────────────────────

@app.post("/debug")
async def debug_project(request: DebugRequest):
    """Build and auto-fix errors in an existing project."""
    async def stream():
        async for event in debug_only(
            request.project_path,
            request.command or "dotnet build",
            request.error_output or "",
        ):
            yield event

    return StreamingResponse(stream(), media_type="text/event-stream")


# ── Evolution ───────────────────────────────────────────────────────────────

@app.post("/evolve")
async def evolve_project(request: EvolutionRequest):
    """Run code quality evolution analysis on an existing project."""
    async def stream():
        async for event in evolve(request.project_path, request.checks):
            yield event

    return StreamingResponse(stream(), media_type="text/event-stream")


# ── Project Memory ───────────────────────────────────────────────────────────

@app.get("/memory/{project_path:path}", response_model=ProjectMemoryResponse)
async def get_memory(project_path: str):
    mem = await memory.load(project_path)
    if not mem:
        raise HTTPException(404, "Project not found in memory")
    return ProjectMemoryResponse(**{k: v for k, v in mem.items() if k != "path"})


@app.get("/memory/{project_path:path}/events")
async def get_events(project_path: str, limit: int = 50):
    return await memory.get_events(project_path, limit)


@app.delete("/memory/{project_path:path}")
async def delete_memory(project_path: str):
    async with await memory._db() as db:
        await db.execute("DELETE FROM projects WHERE path=?", (project_path,))
        await db.execute("DELETE FROM events WHERE project_path=?", (project_path,))
        await db.commit()
    return {"deleted": project_path}


# ── Context ──────────────────────────────────────────────────────────────────

@app.get("/context/{project_path:path}")
async def get_context(project_path: str):
    index = context.index_project(project_path)
    return {"structure": index["structure"], "summary": index["summary"], "file_count": len(index["files"])}


# ── Ollama ───────────────────────────────────────────────────────────────────

@app.get("/models")
async def list_models():
    models = await ollama.list_models()
    return {"models": models}


# ── Evolution config ─────────────────────────────────────────────────────────

@app.get("/evolution/config")
async def get_evolution_config():
    return _EVO_CFG


@app.post("/evolution/toggle")
async def toggle_evolution(enabled: bool):
    _EVO_CFG["enabled"] = enabled
    if enabled and not scheduler.running:
        scheduler.start()
    elif not enabled and scheduler.running:
        scheduler.shutdown(wait=False)
    return {"evolution_enabled": enabled}
