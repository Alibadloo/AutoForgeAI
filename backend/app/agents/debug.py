from __future__ import annotations
import re
from typing import AsyncIterator
from .base import BaseAgent
from ..core import ollama, memory, terminal, context
from ..models.schemas import AgentName, EventType

MAX_ITERATIONS = 5


class DebugAgent(BaseAgent):
    name = AgentName.DEBUG
    role = "reviewer"

    async def run(self, task: dict) -> AsyncIterator[str]:
        build_command: str = task.get("command", "dotnet build")
        cwd: str = task.get("cwd", self.project_path)
        error_output: str = task.get("error_output", "")
        rules_text = await self._rules_prompt()

        yield self._emit(EventType.AGENT_START, f"Debug Agent started — build: {build_command}")

        # If error was pre-supplied, skip the first build
        if not error_output:
            yield self._emit(EventType.COMMAND_RUN, f"Running: {build_command}", {"command": build_command})
            result = await terminal.run(build_command, cwd=cwd)
            yield self._emit(EventType.COMMAND_OUTPUT, result.output[:1000], {"returncode": result.returncode})

            if result.success:
                yield self._emit(EventType.BUILD_SUCCESS, "Build succeeded — no errors found")
                return
            error_output = result.output

        for iteration in range(1, MAX_ITERATIONS + 1):
            yield self._log(f"Debug iteration {iteration}/{MAX_ITERATIONS}")

            errors = _parse_errors(error_output)
            if not errors:
                yield self._log("No parseable errors found in output")
                break

            yield self._log(f"Found {len(errors)} error(s) to fix")

            # Gather context for affected files
            affected_files = _extract_file_paths(error_output)
            file_contents: dict[str, str] = {}
            for fp in affected_files[:5]:
                import os
                abs_fp = fp if os.path.isabs(fp) else os.path.join(self.project_path, fp)
                content = context.read_file(abs_fp)
                if content:
                    file_contents[fp] = content

            system = f"""You are a senior C# debugging expert.
Analyze build errors and provide exact file fixes.
{rules_text}

Output ONLY fixed files using:
// FILE: relative/path/File.cs
<corrected full file content>

Do not explain — just output the fixed files."""

            error_summary = "\n".join(f"  - {e}" for e in errors[:15])
            file_context = "\n\n".join(
                f"// FILE: {fp}\n{content}" for fp, content in file_contents.items()
            )

            prompt = f"""Fix these C# build errors:

ERRORS:
{error_summary}

AFFECTED FILES:
{file_context or '(no file context available)'}

FULL BUILD OUTPUT:
{error_output[:2000]}

Output the complete corrected file(s). Fix ALL errors shown."""

            yield self._log("Asking Ollama to fix errors…")
            response = await self._ask(prompt, system=system)
            fixed_files = ollama.extract_files(response)

            if not fixed_files:
                yield self._log("⚠ Could not extract fix from Ollama response")
                break

            for rel_path, content in fixed_files:
                success = self._write_file(rel_path, content)
                if success:
                    yield self._file_modified(rel_path)
                    await memory.log_event(self.project_path, "debug", "FIX", f"Fixed {rel_path}")

            # Re-run build
            yield self._emit(EventType.COMMAND_RUN, f"Re-running: {build_command}", {"command": build_command})
            result = await terminal.run(build_command, cwd=cwd)
            yield self._emit(EventType.COMMAND_OUTPUT, result.output[:1000], {"returncode": result.returncode})

            if result.success:
                yield self._emit(EventType.BUILD_SUCCESS, f"✅ Build succeeded after {iteration} fix(es)!")
                await memory.add_decision(
                    self.project_path,
                    f"Debug Agent fixed {len(fixed_files)} file(s) after {iteration} iteration(s)"
                )
                return

            error_output = result.output

        yield self._emit(
            EventType.BUILD_ERROR,
            f"Could not fix build after {MAX_ITERATIONS} iterations. Manual intervention needed.",
            {"last_errors": _parse_errors(error_output)[:5]}
        )
        yield self._emit(EventType.AGENT_DONE, "Debug Agent finished")


def _parse_errors(output: str) -> list[str]:
    """Extract error lines from build output."""
    error_pattern = re.compile(r".*?error\s+[A-Z]{2,}\d+.*", re.IGNORECASE)
    lines = output.split("\n")
    errors = [l.strip() for l in lines if error_pattern.match(l.strip())]
    return list(dict.fromkeys(errors))  # deduplicate, preserve order


def _extract_file_paths(output: str) -> list[str]:
    """Extract referenced file paths from build output."""
    # Match patterns like: src/Controllers/MyController.cs(42,15)
    pattern = re.compile(r"([^\s]+\.cs)\(\d+,\d+\)")
    matches = pattern.findall(output)
    return list(dict.fromkeys(matches))
