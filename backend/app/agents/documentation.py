from __future__ import annotations
from typing import AsyncIterator
from .base import BaseAgent
from ..core import ollama, memory, context
from ..models.schemas import AgentName, EventType


class DocumentationAgent(BaseAgent):
    name = AgentName.DOCUMENTATION
    role = "fast"

    async def run(self, task: dict) -> AsyncIterator[str]:
        yield self._emit(EventType.AGENT_START, "Generating documentation…")

        mem = await self._memory()
        plan: dict = task.get("plan", {})
        project_name = mem.get("name", plan.get("project_name", "Project"))
        description = mem.get("description", plan.get("description", ""))
        tech_stack = mem.get("tech_stack", plan.get("tech_stack", {}))
        architecture = mem.get("architecture", plan.get("architecture_pattern", ""))
        decisions = mem.get("decisions", [])
        endpoints = plan.get("api_endpoints", [])
        entities = plan.get("database_entities", [])
        file_index = context.index_project(self.project_path)

        system = "You are a technical writer. Generate clean, professional documentation in Markdown."

        # ── README ───────────────────────────────────────────────────────────
        yield self._log("Generating README.md…")

        readme_prompt = f"""Generate a professional README.md for:

Project: {project_name}
Description: {description}
Architecture: {architecture}
Tech Stack: {tech_stack}
Project Structure:
{file_index['structure']}

API Endpoints: {endpoints}

Include:
1. Project title + description with badges
2. Features list
3. Architecture overview
4. Tech stack table
5. Getting Started (prerequisites, install, run)
6. API endpoints table
7. Database schema overview
8. Project structure tree
9. Contributing section
10. License (MIT)

Make it look professional and impressive for GitHub."""

        readme = await self._ask(readme_prompt, system=system)
        readme_blocks = ollama.extract_code_blocks(readme, "markdown")
        readme_content = readme_blocks[0] if readme_blocks else readme

        self._write_file("README.md", readme_content)
        await memory.append_file(self.project_path, "README.md")
        yield self._file_created("README.md")

        # ── ARCHITECTURE ──────────────────────────────────────────────────────
        yield self._log("Generating ARCHITECTURE.md…")

        arch_prompt = f"""Generate ARCHITECTURE.md for {project_name}.

Architecture: {architecture}
Tech Stack: {tech_stack}
Decisions made:
{chr(10).join(f'- {d}' for d in decisions)}

Include:
1. Architecture diagram (ASCII)
2. Layer descriptions
3. Component interactions
4. Data flow
5. Design patterns used
6. Why these decisions were made"""

        arch_content = await self._ask(arch_prompt, system=system)
        self._write_file("docs/ARCHITECTURE.md", arch_content)
        yield self._file_created("docs/ARCHITECTURE.md")

        # ── API DOCS ──────────────────────────────────────────────────────────
        if endpoints:
            yield self._log("Generating API.md…")
            api_prompt = f"""Generate complete API documentation in Markdown for {project_name}.

Endpoints:
{endpoints}

Entities:
{entities}

Include for each endpoint:
- Method + URL
- Description
- Request body (JSON example)
- Response (JSON example)
- Possible error codes"""

            api_content = await self._ask(api_prompt, system=system)
            self._write_file("docs/API.md", api_content)
            yield self._file_created("docs/API.md")

        yield self._emit(EventType.AGENT_DONE, "Documentation generated: README.md, ARCHITECTURE.md, API.md")
