from __future__ import annotations
import asyncio
import json
from typing import AsyncIterator
from ..models.schemas import ForgeRequest, AgentName, EventType, SSEEvent
from . import memory, ollama
from ..agents.base import sse


def _sse(event_type: EventType, agent: str, message: str, data: dict | None = None) -> str:
    return sse(event_type, agent, message, data)


async def forge(request: ForgeRequest) -> AsyncIterator[str]:
    """
    Main orchestration pipeline. Yields SSE events.

    Flow:
    1. ArchitectAgent   → design architecture + plan
    2. DatabaseAgent    → schema + migrations
    3. BackendAgent     → C# API code
    4. FrontendAgent    → React frontend code
    5. DebugAgent       → build + fix loop
    6. DocumentationAgent → README + docs
    7. GitAgent         → init repo + initial commit
    """
    project_path = request.project_path
    enabled = request.agents_enabled or [a for a in AgentName]

    # Initialize project memory
    await memory.init_db()
    existing = await memory.load(project_path)
    if not existing:
        await memory.save(project_path, {
            "name": "Project",
            "description": request.prompt[:100],
            "tech_stack": request.tech_stack or {},
            "architecture": "",
            "decisions": [],
            "rules": request.rules or [],
            "todo": [],
            "files": [],
        })

    yield _sse(EventType.LOG, "orchestrator", f"Starting AutoForge AI for: {project_path}")
    yield _sse(EventType.LOG, "orchestrator", f"Enabled agents: {[a.value for a in enabled]}")

    plan: dict = {}

    # ── 1. ARCHITECT ──────────────────────────────────────────────────────────
    if AgentName.ARCHITECT in enabled:
        from ..agents.architect import ArchitectAgent
        agent = ArchitectAgent(project_path)
        task = {
            "prompt": request.prompt,
            "tech_stack": request.tech_stack or {},
            "rules": request.rules or [],
        }
        async for event in agent.run(task):
            yield event
            # Extract plan from agent_done event
            try:
                parsed = json.loads(event.removeprefix("data: "))
                if parsed.get("type") == EventType.AGENT_DONE.value:
                    plan = parsed.get("data", {}).get("plan", {})
            except Exception:
                pass

    if not plan:
        if AgentName.ARCHITECT not in enabled:
            # Architect was skipped — build a minimal plan from the request
            from ..agents.architect import _build_fallback_plan
            plan = _build_fallback_plan(request.prompt, request.tech_stack or {}, request.rules or [])
            yield _sse(EventType.LOG, "orchestrator", f"Using auto-plan: {plan['project_name']}")
            await memory.save(project_path, {
                "name": plan["project_name"],
                "description": plan["description"],
                "tech_stack": plan["tech_stack"],
                "architecture": plan["architecture_pattern"],
                "decisions": plan["decisions"],
                "rules": plan["rules"],
                "todo": [],
                "files": [],
            })
        else:
            yield _sse(EventType.FORGE_ERROR, "orchestrator", "Architecture plan not received — aborting")
            return

    yield _sse(EventType.LOG, "orchestrator", f"Plan ready: {plan.get('project_name')}")

    # ── 2. DATABASE ───────────────────────────────────────────────────────────
    if AgentName.DATABASE in enabled:
        from ..agents.database import DatabaseAgent
        async for event in DatabaseAgent(project_path).run({"plan": plan}):
            yield event

    # ── 3. BACKEND ────────────────────────────────────────────────────────────
    if AgentName.BACKEND in enabled:
        from ..agents.backend import BackendAgent
        async for event in BackendAgent(project_path).run({"plan": plan}):
            yield event

    # ── 4. FRONTEND ───────────────────────────────────────────────────────────
    if AgentName.FRONTEND in enabled:
        from ..agents.frontend import FrontendAgent
        async for event in FrontendAgent(project_path).run({"plan": plan}):
            yield event

    # ── 5. DEBUG (auto build+fix) ─────────────────────────────────────────────
    if AgentName.DEBUG in enabled:
        from ..agents.debug import DebugAgent
        import os

        # Try to detect the primary .csproj to determine build dir
        build_cwd = project_path
        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if d not in ("node_modules", "bin", "obj")]
            for f in files:
                if f.endswith(".csproj"):
                    build_cwd = root
                    break
            break  # only check top level

        async for event in DebugAgent(project_path).run({
            "command": "dotnet build",
            "cwd": build_cwd,
        }):
            yield event

    # ── 6. DOCUMENTATION ──────────────────────────────────────────────────────
    if AgentName.DOCUMENTATION in enabled:
        from ..agents.documentation import DocumentationAgent
        async for event in DocumentationAgent(project_path).run({"plan": plan}):
            yield event

    # ── 7. GIT ─────────────────────────────────────────────────────────────────
    if AgentName.GIT in enabled:
        from ..agents.git_agent import GitAgent
        async for event in GitAgent(project_path).run({"action": "init"}):
            yield event

    yield _sse(EventType.FORGE_COMPLETE, "orchestrator",
               f"AutoForge AI complete! Project forged at {project_path}", {"plan": plan})


async def debug_only(project_path: str, command: str, error_output: str = "") -> AsyncIterator[str]:
    """Run only the Debug agent on an existing project."""
    from ..agents.debug import DebugAgent
    async for event in DebugAgent(project_path).run({
        "command": command,
        "cwd": project_path,
        "error_output": error_output,
    }):
        yield event


async def evolve(project_path: str, checks: list[str] | None = None) -> AsyncIterator[str]:
    """Run evolution analysis and apply HIGH priority fixes."""
    from . import evolution

    yield _sse(EventType.LOG, "evolution", "Starting evolution analysis…")
    findings = await evolution.run_evolution(project_path, checks)

    if not findings:
        yield _sse(EventType.LOG, "evolution", "No issues found — project is clean!")
        return

    yield _sse(EventType.LOG, "evolution", f"Found {len(findings)} issue(s)", {"findings": findings})

    modified = await evolution.apply_evolution_fixes(project_path, findings)
    if modified:
        yield _sse(EventType.LOG, "evolution", f"Applied fixes to: {', '.join(modified)}")
    else:
        yield _sse(EventType.LOG, "evolution", "No HIGH priority fixes to apply automatically")

    yield _sse(EventType.FORGE_COMPLETE, "evolution", "Evolution run complete", {"findings": findings, "fixed": modified})
