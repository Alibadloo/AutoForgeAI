from __future__ import annotations
from typing import AsyncIterator
from .base import BaseAgent
from ..core import ollama, memory, terminal
from ..models.schemas import AgentName, EventType


def _detect_language(tech_stack: dict) -> str:
    """Detect primary language from tech stack."""
    backend = (tech_stack.get("backend") or "").lower()
    if "python" in backend:
        return "python"
    if "node" in backend or "javascript" in backend or "typescript" in backend:
        return "typescript"
    if "go" in backend or "golang" in backend:
        return "go"
    if "java" in backend and "spring" in backend:
        return "java"
    return "csharp"  # default


def _system_prompt(lang: str, arch_pattern: str, rules_text: str) -> str:
    if lang == "python":
        return f"""You are a senior Python developer.
Generate complete, runnable Python code following {arch_pattern}.
{rules_text}

Use:
- Type hints everywhere
- Dataclasses or Pydantic models
- pathlib for paths
- Clean module structure

Output files using:
# FILE: relative/path/to/file.py
<file content>
"""
    if lang == "typescript":
        return f"""You are a senior TypeScript/Node.js developer.
Generate complete TypeScript code following {arch_pattern}.
{rules_text}

Output files using:
// FILE: relative/path/to/file.ts
<file content>
"""
    # default C#
    return f"""You are a senior C# .NET 8 developer.
Generate production-ready C# code following {arch_pattern}.
{rules_text}

Use async/await, Dependency Injection, Interface-based abstractions.

Output files using:
// FILE: relative/path/to/File.cs
<file content>
"""


def _code_prompt(lang: str, project_name: str, tech_stack: dict,
                 arch_pattern: str, folder_structure: str,
                 entities: list, endpoints: list, tasks: list) -> str:
    ext = {"python": "py", "typescript": "ts"}.get(lang, "cs")
    lang_name = {"python": "Python 3.12", "typescript": "TypeScript", "csharp": "C# .NET 8"}.get(lang, lang)

    task_str = ", ".join(tasks[:4]) if tasks else "implement the project"

    return f"""Write a complete {lang_name} program for: {project_name}

Tasks: {task_str}
Tech: {tech_stack.get('backend', lang_name)}

For each file use EXACTLY this format:
// FILE: src/filename.{ext}
<complete file content>

// FILE: src/another.{ext}
<complete file content>

Write 2-3 complete, working files. Include main entry point and core logic."""


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
            task.get("tasks", ["Create project"])
        )
        project_name = mem.get("name", plan.get("project_name", "MyProject"))
        entities = plan.get("database_entities", [])
        endpoints = plan.get("api_endpoints", [])
        arch_pattern = mem.get("architecture", plan.get("architecture_pattern", "Clean Architecture"))
        folder_structure = "\n".join(plan.get("folder_structure", []))

        lang = _detect_language(tech_stack)
        yield self._log(f"Project: {project_name} | Lang: {lang} | Pattern: {arch_pattern}")
        yield self._log(f"Tasks: {', '.join(backend_tasks)}")

        system = _system_prompt(lang, arch_pattern, rules_text)
        prompt = _code_prompt(lang, project_name, tech_stack, arch_pattern,
                              folder_structure, entities, endpoints, backend_tasks)

        yield self._log("Generating code with Ollama…")
        response = await self._ask(prompt, system=system)

        files = ollama.extract_files(response)

        if not files:
            # Try language-specific code blocks only (ignore bash/shell)
            lang_ext = {"python": "python", "typescript": "typescript", "csharp": "csharp"}
            blocks = ollama.extract_code_blocks(response, lang_ext.get(lang, ""))
            if not blocks:
                # Also try generic blocks that aren't bash/shell
                all_blocks = ollama.extract_code_blocks(response)
                blocks = [b for b in all_blocks if not b.strip().startswith(("├", "└", "│", "G:\\", "G:/", ".git", "PascalCase"))]

            if blocks and len(blocks[0]) > 100:
                yield self._log(f"No FILE markers — using {len(blocks)} code block(s)")
                ext = {"python": "py", "typescript": "ts"}.get(lang, "cs")
                for i, block in enumerate(blocks[:3]):
                    fname = f"src/main.{ext}" if i == 0 else f"src/module_{i}.{ext}"
                    success = self._write_file(fname, block)
                    if success:
                        yield self._file_created(fname)
                        await memory.append_file(self.project_path, fname)
            else:
                # Retry with a simpler, more direct prompt
                yield self._log("Retrying with direct prompt…")
                lang_name = {"python": "Python", "typescript": "TypeScript"}.get(lang, "C#")
                simple_prompt = f"""Write a complete {lang_name} {project_name} application.
Tasks: {', '.join(backend_tasks[:3])}
Tech: {tech_stack.get('backend','')}

For EACH file, use this exact format:
// FILE: src/filename.{'py' if lang=='python' else 'ts' if lang=='typescript' else 'cs'}
<complete file content here>

Write at least 2-3 files with real working code."""
                response2 = await self._ask(simple_prompt, system=system)
                files = ollama.extract_files(response2)
                if not files:
                    yield self._emit(EventType.AGENT_ERROR, "No code generated after retry")
                    return

        yield self._log(f"Writing {len(files)} files…")
        for rel_path, content in files:
            # Skip files with spaces in their names (LLM artifact)
            if " " in rel_path.split("/")[-1]:
                clean = rel_path.replace(" ", "")
                yield self._log(f"Fixed filename: {rel_path} → {clean}")
                rel_path = clean
            success = self._write_file(rel_path, content)
            if success:
                await memory.append_file(self.project_path, rel_path)
                yield self._file_created(rel_path)
            else:
                yield self._log(f"⚠ Failed to write {rel_path}")

        yield self._emit(EventType.AGENT_DONE, f"Backend complete: {len(files)} files | Language: {lang}")
