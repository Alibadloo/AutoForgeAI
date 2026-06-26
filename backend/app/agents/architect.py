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
            "Output ONLY valid JSON. No markdown fences, no explanation. "
            "Start with { and end with }. "
            "Fill ALL placeholder values with real content based on the project."
        )

        tech_hint = tech_stack.get("custom", "") or ", ".join(
            f"{k}: {v}" for k, v in tech_stack.items() if v
        ) or "choose best fit"

        # Extract a sensible name from the prompt
        words = [w.capitalize() for w in prompt_text.replace(",", "").split() if len(w) > 2]
        name_hint = "".join(words[:3]) if words else "MyProject"

        prompt = f"""Design the software architecture for this project and return JSON.

PROJECT REQUEST: {prompt_text}
SUGGESTED TECH: {tech_hint}

Return this JSON with ALL values filled in (replace every placeholder with real content):

{{
  "project_name": "{name_hint}",
  "description": "what this project does in one sentence",
  "tech_stack": {{"backend": "actual tech", "frontend": "actual tech or None", "database": "actual tech or None", "auth": "None"}},
  "architecture_pattern": "Layered Architecture",
  "folder_structure": ["src/", "tests/"],
  "database_entities": [],
  "api_endpoints": [],
  "agent_tasks": {{
    "database": [],
    "backend": ["write main entry point", "write core logic", "write tests"],
    "frontend": [],
    "git": ["init repo", "initial commit"]
  }},
  "decisions": ["why this architecture was chosen"],
  "rules": {extra_rules or []}
}}

IMPORTANT: Use the actual project name, not "PascalCaseName". Fill in real tech stack values."""

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
    words = [w for w in prompt.replace(",", "").split() if len(w) > 2]
    name = "".join(w.capitalize() for w in words[:3]) or "MyProject"
    # Remove generic placeholder words
    for placeholder in ("PascalCasename", "PascalCaseName", "Projectname"):
        name = name.replace(placeholder, "")
    name = name or "MyProject"

    # Detect language from prompt if tech_stack is empty
    if not tech_stack:
        prompt_lower = prompt.lower()
        if "python" in prompt_lower:
            tech_stack = {"backend": "Python 3.12", "frontend": "CLI", "database": "JSON", "auth": "None"}
        elif "node" in prompt_lower or "javascript" in prompt_lower:
            tech_stack = {"backend": "Node.js + TypeScript", "frontend": "None", "database": "SQLite", "auth": "None"}
        else:
            tech_stack = {"backend": "C# .NET 8 Web API", "frontend": "React + TypeScript", "database": "SQLite + EF Core", "auth": "JWT"}

    return {
        "project_name": name,
        "description": prompt[:100],
        "tech_stack": tech_stack,
        "architecture_pattern": "Clean Architecture",
        "folder_structure": ["src/Domain/", "src/Application/", "src/Infrastructure/", "src/API/"],
        "database_entities": [],
        "api_endpoints": [],
        "agent_tasks": {
            "database": [],
            "backend": [f"Implement: {prompt[:80]}"],
            "frontend": [],
            "git": ["Initialize repository", "Initial commit"],
        },
        "decisions": ["Fallback plan — Ollama did not return parseable JSON"],
        "rules": rules,
    }
