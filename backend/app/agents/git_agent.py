from __future__ import annotations
from typing import AsyncIterator
from .base import BaseAgent
from ..core import terminal, memory, ollama
from ..models.schemas import AgentName, EventType


GITIGNORE_DOTNET = """# .NET
bin/
obj/
*.user
*.suo
.vs/
*.db
appsettings.Development.json

# Node
node_modules/
dist/
.next/

# Python
__pycache__/
*.pyc
venv/
.env

# OS
.DS_Store
Thumbs.db
"""


class GitAgent(BaseAgent):
    name = AgentName.GIT
    role = "fast"

    async def run(self, task: dict) -> AsyncIterator[str]:
        action: str = task.get("action", "init")

        if action == "init":
            async for event in self._init():
                yield event
        elif action == "commit":
            async for event in self._commit(task.get("message", "")):
                yield event
        elif action == "branch":
            async for event in self._branch(task.get("branch_name", "feature/autoforge")):
                yield event
        else:
            yield self._log(f"Unknown git action: {action}")

    async def _init(self) -> AsyncIterator[str]:
        yield self._emit(EventType.AGENT_START, "Initializing git repository…")

        # Write .gitignore
        self._write_file(".gitignore", GITIGNORE_DOTNET)
        yield self._file_created(".gitignore")

        # git init
        r = await terminal.run("git init", cwd=self.project_path)
        yield self._emit(EventType.COMMAND_OUTPUT, r.output[:300], {"success": r.success})

        # Configure identity
        await terminal.run('git config user.name "AutoForge AI"', cwd=self.project_path)
        await terminal.run('git config user.email "autoforge@local"', cwd=self.project_path)

        # Initial commit
        await terminal.run("git add .", cwd=self.project_path)
        r2 = await terminal.run('git commit -m "Initial commit by AutoForge AI"', cwd=self.project_path)
        yield self._emit(EventType.COMMAND_OUTPUT, r2.output[:300], {"success": r2.success})

        if r2.success:
            await memory.add_decision(self.project_path, "Git repository initialized")
            yield self._emit(EventType.AGENT_DONE, "✅ Git repository initialized with initial commit")
        else:
            yield self._emit(EventType.AGENT_ERROR, f"Git init failed: {r2.stderr[:200]}")

    async def _commit(self, message: str) -> AsyncIterator[str]:
        yield self._emit(EventType.AGENT_START, "Creating git commit…")

        if not message:
            # Auto-generate commit message
            mem = await self._memory()
            files = mem.get("files", [])
            recent = files[-5:] if files else []
            prompt = f"""Write a concise git commit message (max 72 chars) for these changes:
Project: {mem.get('name', 'Project')}
Recent files modified: {recent}
Be specific and use conventional commits format (feat:, fix:, refactor:, etc.)
Return ONLY the commit message, nothing else."""
            message = await self._ask(prompt, role="fast")
            message = message.strip().strip('"').strip("'")[:72]

        yield self._log(f"Commit message: {message}")

        r1 = await terminal.run("git add .", cwd=self.project_path)
        r2 = await terminal.run(f'git commit -m "{message}"', cwd=self.project_path)

        yield self._emit(EventType.COMMAND_OUTPUT, r2.output[:300], {"success": r2.success})
        if r2.success:
            yield self._emit(EventType.AGENT_DONE, f"✅ Committed: {message}")
        else:
            yield self._emit(EventType.AGENT_ERROR, r2.stderr[:200])

    async def _branch(self, branch_name: str) -> AsyncIterator[str]:
        yield self._emit(EventType.AGENT_START, f"Creating branch: {branch_name}")
        r = await terminal.run(f"git checkout -b {branch_name}", cwd=self.project_path)
        yield self._emit(EventType.COMMAND_OUTPUT, r.output[:300], {"success": r.success})
        if r.success:
            yield self._emit(EventType.AGENT_DONE, f"✅ Branch created: {branch_name}")
