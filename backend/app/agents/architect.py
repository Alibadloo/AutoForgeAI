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

        system = (
            "You are a software architect. "
            "Output ONLY valid JSON — no explanation, no markdown, no extra text. "
            "Start your response with { and end with }."
        )

        tech_hint = tech_stack.get("custom", "") or ", ".join(
            f"{k}: {v}" for k, v in tech_stack.items() if v
        ) or "choose best fit"

        prompt = f"""Design architecture for this project. Output ONLY JSON.

PROJECT: {prompt_text}
TECH: {tech_hint}

JSON structure (fill in values, keep all keys):
{{
  "project_name": "PascalCaseName",
  "description": "one sentence",
  "tech_stack": {{"backend": "...", "frontend": "...", "database": "...", "auth": "..."}},
  "architecture_pattern": "Clean Architecture",
  "folder_structure": ["src/", "tests/"],
  "database_entities": [{{"name": "Entity", "fields": ["Id:int", "Name:string"]}}],
  "api_endpoints": [{{"method": "GET", "path": "/api/items", "description": "list items"}}],
  "agent_tasks": {{
    "database": ["create schema"],
    "backend": ["create API"],
    "frontend": ["create UI"],
    "git": ["init repo"]
  }},
  "decisions": ["reason 1"],
  "rules": {extra_rules or []}
}}"""

        yield self._log("Querying Ollama for architecture plan…")

        response = await self._ask(prompt, system=system)
        plan = ollama.extract_json(response)

        if not plan:
            # Fallback: build a minimal plan from the prompt
            yield self._log("JSON parse failed — building minimal plan from prompt…")
            plan = _build_fallback_plan(prompt_text, tech_stack, extra_rules)
            yield self._log(f"Using fallback plan: {plan['project_name']}")

        # Ensure required keys exist
        plan.setdefault("agent_tasks", {
            "database": ["Create database schema"],
            "backend": ["Create API project"],
            "frontend": ["Create frontend project"],
            "git": ["Initialize repository"],
        })
        plan.setdefault("database_entities", [])
        plan.setdefault("api_endpoints", [])
        plan.setdefault("folder_structure", ["src/"])
        plan.setdefault("decisions", [])
        plan.setdefault("rules", extra_rules)

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
            f"Architecture: {plan.get('project_name')} ({plan.get('architecture_pattern', 'N/A')})",
            {"plan": plan}
        )


def _build_fallback_plan(prompt: str, tech_stack: dict, rules: list) -> dict:
    """Minimal plan used when Ollama returns unparseable JSON."""
    name = "".join(w.capitalize() for w in prompt.split()[:3]) or "MyProject"
    return {
        "project_name": name,
        "description": prompt[:100],
        "tech_stack": tech_stack or {
            "backend": "C# .NET 8 Web API",
            "frontend": "React + TypeScript",
            "database": "SQLite + EF Core",
            "auth": "JWT",
        },
        "architecture_pattern": "Clean Architecture",
        "folder_structure": ["src/Domain/", "src/Application/", "src/Infrastructure/", "src/API/"],
        "database_entities": [],
        "api_endpoints": [],
        "agent_tasks": {
            "database": ["Create database schema and seed data"],
            "backend": ["Create Domain entities", "Create API controllers"],
            "frontend": ["Create React app with Vite and TypeScript"],
            "git": ["Initialize repository", "Initial commit"],
        },
        "decisions": ["Fallback plan — Ollama did not return parseable JSON"],
        "rules": rules,
    }
