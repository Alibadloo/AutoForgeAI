from __future__ import annotations
from typing import AsyncIterator
from .base import BaseAgent
from ..core import ollama, memory, rules
from ..models.schemas import AgentName, EventType


class ArchitectAgent(BaseAgent):
    name = AgentName.ARCHITECT
    role = "planner"

    async def run(self, task: dict) -> AsyncIterator[str]:
        prompt_text: str = task.get("prompt", "")
        tech_stack: dict = task.get("tech_stack", {})
        extra_rules: list[str] = task.get("rules", [])

        yield self._emit(EventType.AGENT_START, "Analyzing project requirements…")

        rules_text = rules.format_rules_for_prompt(extra_rules) if extra_rules else ""

        system = """You are a senior software architect.
Analyze the project request and produce a complete architecture plan in JSON.
Be specific, practical, and production-ready."""

        prompt = f"""Analyze this project and design the architecture:

REQUEST: {prompt_text}

PREFERRED TECH STACK: {tech_stack or 'Choose the best fit'}

{rules_text}

Return a JSON with this EXACT structure (no extra text outside JSON):
{{
  "project_name": "PascalCaseName",
  "description": "one sentence",
  "tech_stack": {{
    "backend": "e.g. C# .NET 8 Web API",
    "frontend": "e.g. React 18 + TypeScript + Vite",
    "database": "e.g. PostgreSQL 16 + EF Core",
    "auth": "e.g. JWT Bearer",
    "other": []
  }},
  "architecture_pattern": "e.g. Clean Architecture",
  "folder_structure": [
    "src/Domain/",
    "src/Application/",
    "src/Infrastructure/",
    "src/API/"
  ],
  "database_entities": [
    {{"name": "EntityName", "fields": ["Id:int", "Name:string", "CreatedAt:DateTime"]}}
  ],
  "api_endpoints": [
    {{"method": "GET", "path": "/api/items", "description": "List all items"}}
  ],
  "agent_tasks": {{
    "database": ["Create PostgreSQL schema", "Write EF Core migrations", "Add seed data"],
    "backend": ["Create Domain entities", "Create Repository interfaces", "Create API controllers"],
    "frontend": ["Create React app with Vite", "Create pages: Home, List, Detail", "Add Axios service"],
    "git": ["Initialize repository", "Create .gitignore", "Initial commit"]
  }},
  "decisions": [
    "Using Repository Pattern for data access abstraction",
    "Clean Architecture to keep domain logic independent"
  ],
  "rules": {extra_rules or []}
}}"""

        yield self._log("Querying Ollama for architecture plan…")

        response = await self._ask(prompt, system=system)
        plan = ollama.extract_json(response)

        if not plan:
            yield self._emit(EventType.AGENT_ERROR, "Could not parse architecture JSON from Ollama response")
            yield self._emit(EventType.AGENT_ERROR, f"Raw response: {response[:300]}")
            return

        # Persist to project memory
        await memory.save(self.project_path, {
            "name": plan.get("project_name", "Project"),
            "description": plan.get("description", ""),
            "tech_stack": plan.get("tech_stack", {}),
            "architecture": plan.get("architecture_pattern", ""),
            "decisions": plan.get("decisions", []),
            "rules": plan.get("rules", extra_rules),
            "todo": [],
            "files": [],
        })

        yield self._emit(
            EventType.AGENT_DONE,
            f"Architecture designed: {plan.get('project_name')} ({plan.get('architecture_pattern')})",
            {"plan": plan}
        )
