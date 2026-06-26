from __future__ import annotations
import httpx
import json
import yaml
from pathlib import Path
from typing import AsyncIterator

_cfg = yaml.safe_load(open(Path(__file__).parents[3] / "config.yaml"))
_OLLAMA = _cfg["ollama"]
BASE_URL = _OLLAMA["base_url"]
TIMEOUT = _OLLAMA["timeout"]
MODELS = _OLLAMA["models"]
FALLBACK = _OLLAMA.get("fallback", "llama3.2")


def model_for(role: str) -> str:
    return MODELS.get(role, FALLBACK)


async def generate(prompt: str, role: str = "coder", system: str = "") -> str:
    """Single-shot generation — returns full response text."""
    model = model_for(role)
    payload: dict = {"model": model, "prompt": prompt, "stream": False}
    if system:
        payload["system"] = system

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            r = await client.post(f"{BASE_URL}/api/generate", json=payload)
            r.raise_for_status()
            return r.json().get("response", "")
        except Exception as e:
            # Retry with fallback model
            if model != FALLBACK:
                payload["model"] = FALLBACK
                r = await client.post(f"{BASE_URL}/api/generate", json=payload)
                return r.json().get("response", "")
            raise RuntimeError(f"Ollama error: {e}") from e


async def stream(prompt: str, role: str = "coder", system: str = "") -> AsyncIterator[str]:
    """Streaming generation — yields text chunks."""
    model = model_for(role)
    payload: dict = {"model": model, "prompt": prompt, "stream": True}
    if system:
        payload["system"] = system

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        async with client.stream("POST", f"{BASE_URL}/api/generate", json=payload) as resp:
            async for line in resp.aiter_lines():
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if chunk := data.get("response", ""):
                        yield chunk
                    if data.get("done"):
                        break
                except json.JSONDecodeError:
                    continue


async def list_models() -> list[dict]:
    """Return list of locally available Ollama models."""
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"{BASE_URL}/api/tags")
            return r.json().get("models", [])
    except Exception:
        return []


async def is_online() -> bool:
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            r = await client.get(f"{BASE_URL}/api/tags")
            return r.status_code == 200
    except Exception:
        return False


def extract_json(text: str) -> dict | None:
    """Extract first JSON object from LLM response."""
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except Exception:
            pass
    return None


def extract_code_blocks(text: str, lang: str = "") -> list[str]:
    """Extract all ```lang ... ``` code blocks from LLM response."""
    blocks = []
    marker = f"```{lang}" if lang else "```"
    parts = text.split(marker)
    for i in range(1, len(parts), 2):
        block = parts[i]
        if block.startswith("\n"):
            block = block[1:]
        end = block.find("```")
        if end != -1:
            blocks.append(block[:end].rstrip())
        else:
            blocks.append(block.rstrip())
    return blocks


def extract_files(text: str) -> list[tuple[str, str]]:
    """
    Extract file path + content from LLM output.
    Supports formats:
      // FILE: path/to/file.cs
      <content>
    """
    files: list[tuple[str, str]] = []
    lines = text.split("\n")
    current_path: str | None = None
    current_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        is_path = (
            stripped.startswith("// FILE:") or
            stripped.startswith("# FILE:") or
            stripped.startswith("<!-- FILE:") or
            stripped.startswith("## File:")
        )
        if is_path:
            if current_path and current_lines:
                content = "\n".join(current_lines).strip()
                if content:
                    files.append((current_path, content))
            # Extract path from marker
            for prefix in ["// FILE:", "# FILE:", "<!-- FILE:", "## File:"]:
                if stripped.startswith(prefix):
                    current_path = stripped[len(prefix):].strip().strip(">").strip()
                    break
            current_lines = []
        else:
            if current_path is not None:
                current_lines.append(line)

    if current_path and current_lines:
        content = "\n".join(current_lines).strip()
        if content:
            files.append((current_path, content))

    return files
