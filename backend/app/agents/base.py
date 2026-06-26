from __future__ import annotations
import json
from abc import ABC, abstractmethod
from typing import AsyncIterator
from ..core import ollama, memory, context, rules
from ..models.schemas import SSEEvent, EventType, AgentName


def sse(event_type: EventType, agent: str, message: str, data: dict | None = None) -> str:
    """Format a Server-Sent Event string."""
    payload = SSEEvent(type=event_type, agent=agent, message=message, data=data or {})
    return f"data: {payload.model_dump_json()}\n\n"


class BaseAgent(ABC):
    name: AgentName
    role: str = "coder"       # Ollama model role

    def __init__(self, project_path: str):
        self.project_path = project_path

    # ── Override in subclasses ──────────────────────────────────────────────

    @abstractmethod
    async def run(self, task: dict) -> AsyncIterator[str]:
        """
        Execute the agent's task.
        Yields SSE event strings.
        task: arbitrary dict with task-specific data from the ArchitectAgent plan.
        """
        ...

    # ── Shared helpers ──────────────────────────────────────────────────────

    async def _memory(self) -> dict:
        return await memory.load(self.project_path) or {}

    async def _rules_prompt(self) -> str:
        return await rules.get_rules_prompt(self.project_path)

    def _context(self, focus: str = "") -> str:
        return context.build_context_prompt(self.project_path, focus)

    async def _ask(self, prompt: str, system: str = "") -> str:
        return await ollama.generate(prompt, role=self.role, system=system)

    def _write_file(self, rel_path: str, content: str) -> bool:
        import os
        abs_path = os.path.join(self.project_path, rel_path.lstrip("/\\"))
        return context.write_file(abs_path, content)

    def _emit(self, event_type: EventType, message: str, data: dict | None = None) -> str:
        return sse(event_type, self.name.value, message, data)

    def _log(self, message: str) -> str:
        return self._emit(EventType.LOG, message)

    def _file_created(self, path: str) -> str:
        return self._emit(EventType.FILE_CREATED, f"Created {path}", {"path": path})

    def _file_modified(self, path: str) -> str:
        return self._emit(EventType.FILE_MODIFIED, f"Modified {path}", {"path": path})

    async def _log_to_memory(self, message: str) -> None:
        await memory.log_event(self.project_path, self.name.value, "LOG", message)
