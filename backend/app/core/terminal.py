from __future__ import annotations
import asyncio
import shlex
import yaml
from pathlib import Path
from dataclasses import dataclass

_cfg = yaml.safe_load(open(Path(__file__).parents[2] / "config.yaml"))
_TERMINAL_CFG = _cfg.get("terminal", {})
ALLOWED_PREFIXES: list[str] = _TERMINAL_CFG.get("allowed_prefixes", [])
TIMEOUT: int = _TERMINAL_CFG.get("timeout_seconds", 120)


@dataclass
class CommandResult:
    command: str
    returncode: int
    stdout: str
    stderr: str
    success: bool

    @property
    def output(self) -> str:
        return (self.stdout + "\n" + self.stderr).strip()


def is_allowed(command: str) -> bool:
    """Check if a command is in the allowed list."""
    cmd_lower = command.strip().lower()
    return any(cmd_lower.startswith(prefix) for prefix in ALLOWED_PREFIXES)


async def run(command: str, cwd: str | None = None) -> CommandResult:
    """
    Execute a shell command asynchronously.
    Returns stdout/stderr and return code.
    """
    if not is_allowed(command):
        return CommandResult(
            command=command, returncode=1,
            stdout="", stderr=f"Command not allowed: {command}",
            success=False
        )

    try:
        if isinstance(command, str):
            parts = shlex.split(command, posix=False)
        else:
            parts = command

        proc = await asyncio.create_subprocess_exec(
            *parts,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=TIMEOUT
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return CommandResult(
                command=command, returncode=124,
                stdout="", stderr=f"Command timed out after {TIMEOUT}s",
                success=False
            )

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        rc = proc.returncode or 0

        return CommandResult(
            command=command, returncode=rc,
            stdout=stdout, stderr=stderr,
            success=rc == 0
        )

    except Exception as e:
        return CommandResult(
            command=command, returncode=1,
            stdout="", stderr=str(e),
            success=False
        )


async def run_sequence(commands: list[str], cwd: str | None = None,
                       stop_on_failure: bool = True) -> list[CommandResult]:
    """Run a sequence of commands, optionally stopping on first failure."""
    results: list[CommandResult] = []
    for cmd in commands:
        result = await run(cmd, cwd=cwd)
        results.append(result)
        if stop_on_failure and not result.success:
            break
    return results
