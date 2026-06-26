from __future__ import annotations
import asyncio
import json
import yaml
import httpx
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

_cfg = yaml.safe_load(open(Path(__file__).parents[1] / "config.yaml"))
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
    from .models.schemas import OllamaModel
    online = await ollama.is_online()
    models_raw = await ollama.list_models() if online else []
    models = [
        OllamaModel(
            name=m.get("name", ""),
            size_gb=round(m.get("size", 0) / 1_000_000_000, 1),
            family=(m.get("details") or {}).get("family", "") if isinstance(m.get("details"), dict) else "",
        )
        for m in models_raw
    ]
    active = _cfg.get("ollama", {}).get("models", {})
    return StatusResponse(
        status="ok" if online else "ollama_offline",
        ollama_online=online,
        models=models,
        active_models=active,
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
    return ProjectMemoryResponse(
        project_name=mem.get("name", ""),
        description=mem.get("description", ""),
        tech_stack=mem.get("tech_stack", {}),
        architecture=mem.get("architecture", ""),
        decisions=mem.get("decisions", []),
        rules=mem.get("rules", []),
        todo=mem.get("todo", []),
        files_created=mem.get("files", []),
        created_at=mem.get("created_at", ""),
        updated_at=mem.get("updated_at", ""),
    )


@app.get("/memory/{project_path:path}/events")
async def get_events(project_path: str, limit: int = 50):
    return await memory.get_events(project_path, limit)


@app.delete("/memory/{project_path:path}")
async def delete_memory(project_path: str):
    async with memory._db() as db:
        await db.execute("DELETE FROM projects WHERE path=?", (project_path,))
        await db.execute("DELETE FROM events WHERE project_path=?", (project_path,))
        await db.commit()
    return {"deleted": project_path}


# ── Context ──────────────────────────────────────────────────────────────────

@app.get("/context/{project_path:path}")
async def get_context(project_path: str):
    index = context.index_project(project_path)
    return {"structure": index["structure"], "summary": index["summary"], "file_count": len(index["files"])}


# ── Ollama / Model Management ────────────────────────────────────────────────

RECOMMENDED_MODELS = [
    {"name": "llama3.2:3b",          "size": "2 GB",  "best_for": "fast tasks, docs, git",        "roles": ["fast"]},
    {"name": "llama3.2:latest",      "size": "2 GB",  "best_for": "general purpose",              "roles": ["planner","coder","reviewer","fast"]},
    {"name": "llama3.1:8b",          "size": "4.7 GB","best_for": "balanced quality + speed",     "roles": ["planner","coder"]},
    {"name": "qwen2.5:7b",           "size": "4.7 GB","best_for": "planning & architecture",      "roles": ["planner"]},
    {"name": "qwen2.5-coder:7b",     "size": "4.7 GB","best_for": "code generation",              "roles": ["coder"]},
    {"name": "qwen2.5-coder:14b",    "size": "9 GB",  "best_for": "advanced code generation",     "roles": ["coder"]},
    {"name": "deepseek-coder-v2:16b","size": "9 GB",  "best_for": "best code generation",         "roles": ["coder","reviewer"]},
    {"name": "codellama:13b",        "size": "7.4 GB","best_for": "code review & debugging",      "roles": ["reviewer"]},
    {"name": "mistral:7b",           "size": "4.1 GB","best_for": "balanced reasoning",           "roles": ["planner","reviewer"]},
    {"name": "gemma2:9b",            "size": "5.5 GB","best_for": "reasoning & planning",         "roles": ["planner"]},
    {"name": "phi4:14b",             "size": "9 GB",  "best_for": "coding + reasoning",           "roles": ["coder","reviewer"]},
    {"name": "llama3.3:70b",         "size": "43 GB", "best_for": "best overall quality",         "roles": ["planner","coder","reviewer"]},
]


@app.get("/models")
async def list_models():
    installed = await ollama.list_models()
    installed_names = {m["name"] for m in installed}
    recommended = [
        {**r, "installed": r["name"] in installed_names}
        for r in RECOMMENDED_MODELS
    ]
    return {"installed": installed, "recommended": recommended}


@app.post("/models/pull")
async def pull_model(body: dict):
    """Stream pull progress for a model. body: {"name": "llama3.2:latest"}"""
    model_name = body.get("name", "")
    if not model_name:
        raise HTTPException(400, "model name required")

    async def stream():
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST", f"{ollama.BASE_URL}/api/pull",
                json={"name": model_name, "stream": True}
            ) as resp:
                async for line in resp.aiter_lines():
                    if line:
                        yield f"data: {line}\n\n"
        yield 'data: {"status":"done"}\n\n'

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.delete("/models/{model_name:path}")
async def delete_model(model_name: str):
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.delete(
            f"{ollama.BASE_URL}/api/delete",
            json={"name": model_name}
        )
    return {"deleted": model_name, "status": r.status_code}


@app.get("/models/config")
async def get_model_config():
    return {"models": _cfg["ollama"]["models"], "fallback": _cfg["ollama"].get("fallback", "")}


@app.put("/models/config")
async def update_model_config(body: dict):
    """Update role→model assignments. body: {"planner": "...", "coder": "...", ...}"""
    allowed = {"planner", "coder", "reviewer", "fast"}
    for role, model in body.items():
        if role in allowed:
            _cfg["ollama"]["models"][role] = model
            ollama.MODELS[role] = model
    return {"updated": {k: v for k, v in body.items() if k in allowed}, "current": ollama.MODELS}


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
