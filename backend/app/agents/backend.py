from __future__ import annotations
from typing import AsyncIterator
from .base import BaseAgent
from ..core import ollama, memory, terminal
from ..models.schemas import AgentName, EventType


class BackendAgent(BaseAgent):
    name = AgentName.BACKEND
    role = "coder"

    async def run(self, task: dict) -> AsyncIterator[str]:
        yield self._emit(EventType.AGENT_START, "Starting backend code generation…")

        mem = await self._memory()
        rules_text = await self._rules_prompt()
        plan: dict = task.get("plan", {})
        tech_stack = mem.get("tech_stack", plan.get("tech_stack", {}))
        backend_tasks: list[str] = (
            plan.get("agent_tasks", {}).get("backend", []) or
            task.get("tasks", ["Create API project"])
        )
        project_name = mem.get("name", plan.get("project_name", "MyProject"))
        entities = plan.get("database_entities", [])
        endpoints = plan.get("api_endpoints", [])
        arch_pattern = mem.get("architecture", plan.get("architecture_pattern", "Clean Architecture"))
        folder_structure = "\n".join(plan.get("folder_structure", []))

        yield self._log(f"Project: {project_name} | Pattern: {arch_pattern}")
        yield self._log(f"Tasks: {', '.join(backend_tasks)}")

        system = f"""You are a senior C# .NET 8 developer.
Generate production-ready, compilable C# code following {arch_pattern}.
{rules_text}

Always use:
- async/await for all I/O
- Dependency Injection
- Interface-based abstractions
- XML doc comments on public methods

Output files using this format:
// FILE: relative/path/to/File.cs
<file content>

// FILE: relative/path/to/Another.cs
<file content>"""

        prompt = f"""Generate the complete backend for this project:

Project: {project_name}
Architecture: {arch_pattern}
Backend: {tech_stack.get('backend', 'C# .NET 8 Web API')}
Database: {tech_stack.get('database', 'PostgreSQL + EF Core')}
Auth: {tech_stack.get('auth', 'JWT Bearer')}

Folder structure:
{folder_structure}

Database entities:
{entities}

API endpoints to implement:
{endpoints}

Tasks to complete:
{chr(10).join(f'- {t}' for t in backend_tasks)}

Generate ALL necessary files: .csproj, Program.cs, Models, Interfaces, Repositories, Services, Controllers, DTOs, Mappings, Middleware.
Make it complete and compilable."""

        yield self._log("Generating backend code with Ollama…")
        response = await self._ask(prompt, system=system)

        files = ollama.extract_files(response)

        if not files:
            # Fallback: try to extract code blocks with paths
            blocks = ollama.extract_code_blocks(response)
            yield self._log(f"Extracted {len(blocks)} code blocks (no file markers found)")
            if blocks:
                yield self._emit(EventType.AGENT_DONE, "Code generated (manual placement needed)", {"code": blocks[0][:500]})
            else:
                yield self._emit(EventType.AGENT_ERROR, "No code generated")
            return

        yield self._log(f"Writing {len(files)} backend files…")
        for rel_path, content in files:
            success = self._write_file(rel_path, content)
            if success:
                await memory.append_file(self.project_path, rel_path)
                yield self._file_created(rel_path)
            else:
                yield self._log(f"⚠ Failed to write {rel_path}")

        yield self._emit(EventType.AGENT_DONE, f"Backend complete: {len(files)} files created")
