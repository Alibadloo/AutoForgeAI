from __future__ import annotations
import asyncio
import yaml
from pathlib import Path
from datetime import datetime
from . import ollama, memory, context, terminal

_cfg = yaml.safe_load(open(Path(__file__).parents[2] / "config.yaml"))
_EVO_CFG = _cfg.get("evolution", {})

CHECKS = _EVO_CFG.get("checks", [
    "duplicate_code", "missing_async", "solid_violations", "slow_queries"
])

CHECK_PROMPTS: dict[str, str] = {
    "duplicate_code": "Find any duplicate or very similar code blocks that should be refactored into shared methods.",
    "missing_async": "Find any synchronous database or I/O operations that should be async/await.",
    "solid_violations": "Find any SOLID principle violations: single responsibility, open/closed, liskov, interface segregation, dependency inversion.",
    "slow_queries": "Find any LINQ queries that could cause N+1 problems or missing Include() calls.",
    "outdated_packages": "Identify any outdated NuGet packages based on common knowledge.",
}


async def run_evolution(project_path: str, checks: list[str] | None = None) -> list[dict]:
    """
    Run evolution analysis on the project.
    Returns a list of findings with suggestions.
    """
    active_checks = checks or CHECKS
    file_index = context.index_project(project_path)
    source_files = [f for f in file_index["files"] if f["lang"] in ("cs", "ts", "tsx")]

    if not source_files:
        return [{"type": "info", "message": "No source files found to analyze"}]

    findings: list[dict] = []

    # Analyze files in batches
    batch_size = 5
    for i in range(0, len(source_files), batch_size):
        batch = source_files[i:i + batch_size]
        file_contents = []
        for f in batch:
            content = context.read_file(f["abs_path"], max_kb=30)
            if content:
                file_contents.append(f"// FILE: {f['path']}\n{content}")

        if not file_contents:
            continue

        combined = "\n\n---\n\n".join(file_contents)
        checks_text = "\n".join(
            f"- {CHECK_PROMPTS.get(c, c)}" for c in active_checks
        )

        prompt = f"""Analyze these source files for the following issues:
{checks_text}

FILES:
{combined[:4000]}

Return a JSON array of findings:
[
  {{
    "type": "duplicate_code|missing_async|solid_violation|slow_query|suggestion",
    "file": "path/to/file.cs",
    "line_hint": "rough description of where",
    "issue": "what is wrong",
    "suggestion": "how to fix it",
    "priority": "HIGH|MEDIUM|LOW"
  }}
]

Return [] if no issues found. Return ONLY JSON."""

        response = await ollama.generate(prompt, role="reviewer")
        parsed = ollama.extract_json(response)

        if isinstance(parsed, list):
            findings.extend(parsed)
        elif isinstance(parsed, dict) and "findings" in parsed:
            findings.extend(parsed["findings"])

    # Log findings to memory
    if findings:
        await memory.add_decision(
            project_path,
            f"Evolution analysis ({datetime.utcnow().strftime('%Y-%m-%d')}): {len(findings)} findings"
        )

    return findings


async def apply_evolution_fixes(project_path: str, findings: list[dict]) -> list[str]:
    """
    Create a new git branch and apply the fixes from evolution analysis.
    Returns list of files modified.
    """
    high_priority = [f for f in findings if f.get("priority") == "HIGH"]
    if not high_priority:
        return []

    branch = f"autoforge/evolution-{datetime.utcnow().strftime('%Y%m%d-%H%M')}"
    await terminal.run(f"git checkout -b {branch}", cwd=project_path)

    modified: list[str] = []
    for finding in high_priority[:5]:  # limit to 5 fixes per run
        file_path = finding.get("file", "")
        if not file_path:
            continue

        import os
        abs_path = os.path.join(project_path, file_path)
        current = context.read_file(abs_path)
        if not current:
            continue

        fix_prompt = f"""Fix this issue in the file:

ISSUE: {finding.get('issue')}
SUGGESTION: {finding.get('suggestion')}
LOCATION: {finding.get('line_hint')}

CURRENT FILE ({file_path}):
{current[:3000]}

Return ONLY the complete corrected file content (no explanation, no FILE: marker)."""

        fixed = await ollama.generate(fix_prompt, role="coder")
        if fixed and len(fixed) > 50:
            context.write_file(abs_path, fixed)
            modified.append(file_path)

    if modified:
        await terminal.run("git add .", cwd=project_path)
        await terminal.run(
            f'git commit -m "AutoForge Evolution: {len(modified)} improvements applied"',
            cwd=project_path
        )

    return modified
