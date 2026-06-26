from __future__ import annotations
from typing import AsyncIterator
from .base import BaseAgent
from ..core import ollama, memory, terminal
from ..models.schemas import AgentName, EventType


class FrontendAgent(BaseAgent):
    name = AgentName.FRONTEND
    role = "coder"

    async def run(self, task: dict) -> AsyncIterator[str]:
        yield self._emit(EventType.AGENT_START, "Starting frontend code generation…")

        mem = await self._memory()
        rules_text = await self._rules_prompt()
        plan: dict = task.get("plan", {})
        tech_stack = mem.get("tech_stack", plan.get("tech_stack", {}))
        frontend_tasks: list[str] = plan.get("agent_tasks", {}).get("frontend", task.get("tasks", []))
        project_name = mem.get("name", plan.get("project_name", "MyProject"))
        entities = plan.get("database_entities", [])
        endpoints = plan.get("api_endpoints", [])
        frontend_tech = tech_stack.get("frontend", "React 18 + TypeScript + Vite + Tailwind CSS")

        yield self._log(f"Frontend stack: {frontend_tech}")

        system = f"""You are a senior React TypeScript developer.
Generate modern, production-ready React code.
{rules_text}

Use:
- Functional components with hooks
- TypeScript strict mode
- Axios for API calls
- React Router v6 for routing
- Clean separation of concerns (pages, components, services, hooks)
- Tailwind CSS for styling

Output files using:
// FILE: frontend/src/path/to/Component.tsx
<content>"""

        prompt = f"""Generate the complete React frontend for:

Project: {project_name}
Frontend: {frontend_tech}
Backend API: http://localhost:5000/api (configurable)

Entities from backend:
{entities}

API endpoints to connect:
{endpoints}

Tasks:
{chr(10).join(f'- {t}' for t in frontend_tasks)}

Generate:
- package.json, vite.config.ts, tsconfig.json
- src/main.tsx, src/App.tsx
- src/services/api.ts (Axios client)
- src/types/index.ts
- One page component per entity (List + Detail)
- Shared Layout, Navbar, Sidebar components
- Loading, Error boundary components

Make it complete with real data fetching, error handling, and routing."""

        yield self._log("Generating frontend code…")
        response = await self._ask(prompt, system=system)
        files = ollama.extract_files(response)

        if not files:
            yield self._emit(EventType.AGENT_ERROR, "No frontend files generated")
            return

        yield self._log(f"Writing {len(files)} frontend files…")
        for rel_path, content in files:
            success = self._write_file(rel_path, content)
            if success:
                await memory.append_file(self.project_path, rel_path)
                yield self._file_created(rel_path)

        # Run npm install if package.json was created
        pkg_created = any("package.json" in p for p, _ in files)
        frontend_dir = None
        for p, _ in files:
            if "package.json" in p:
                import os
                frontend_dir = os.path.join(self.project_path, os.path.dirname(p))
                break

        if pkg_created and frontend_dir:
            yield self._emit(EventType.COMMAND_RUN, "Running npm install…", {"command": "npm install"})
            result = await terminal.run("npm install", cwd=frontend_dir)
            yield self._emit(
                EventType.COMMAND_OUTPUT,
                result.stdout[-500:] if result.stdout else result.stderr[-500:],
                {"success": result.success, "returncode": result.returncode}
            )

        yield self._emit(EventType.AGENT_DONE, f"Frontend complete: {len(files)} files created")
