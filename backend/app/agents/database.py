from __future__ import annotations
from typing import AsyncIterator
from .base import BaseAgent
from ..core import ollama, memory
from ..models.schemas import AgentName, EventType


class DatabaseAgent(BaseAgent):
    name = AgentName.DATABASE
    role = "coder"

    async def run(self, task: dict) -> AsyncIterator[str]:
        yield self._emit(EventType.AGENT_START, "Designing database schema…")

        mem = await self._memory()
        plan: dict = task.get("plan", {})
        rules_text = await self._rules_prompt()
        tech_stack = mem.get("tech_stack", plan.get("tech_stack", {}))
        entities = plan.get("database_entities", task.get("entities", []))
        db_tasks: list[str] = plan.get("agent_tasks", {}).get("database", [])
        db_tech = tech_stack.get("database", "PostgreSQL 16 + EF Core 8")
        project_name = mem.get("name", "Project")

        system = f"""You are a database architect and EF Core specialist.
Design production-ready database schemas with proper indexing and relationships.
{rules_text}

Output SQL and C# migration files using:
// FILE: relative/path/File.sql
<content>

// FILE: relative/path/File.cs
<content>"""

        prompt = f"""Design the complete database for:

Project: {project_name}
Database: {db_tech}

Entities to model:
{entities}

Tasks:
{chr(10).join(f'- {t}' for t in db_tasks)}

Generate:
1. SQL schema file (CREATE TABLE with proper types, indexes, foreign keys)
2. EF Core DbContext with all DbSets
3. EF Core entity configurations (IEntityTypeConfiguration<T>)
4. Initial migration SQL
5. Seed data with realistic sample records
6. Audit fields (CreatedAt, UpdatedAt, IsDeleted) on all tables
7. Proper indexes for common query patterns

Use snake_case for SQL, PascalCase for C# classes."""

        yield self._log("Generating database schema and migrations…")
        response = await self._ask(prompt, system=system)
        files = ollama.extract_files(response)

        if not files:
            yield self._emit(EventType.AGENT_ERROR, "No database files generated")
            return

        yield self._log(f"Writing {len(files)} database files…")
        for rel_path, content in files:
            success = self._write_file(rel_path, content)
            if success:
                await memory.append_file(self.project_path, rel_path)
                yield self._file_created(rel_path)

        yield self._emit(EventType.AGENT_DONE, f"Database schema complete: {len(files)} files")
