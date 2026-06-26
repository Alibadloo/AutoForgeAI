from __future__ import annotations
import os
from pathlib import Path

# Extensions considered "source code" for context indexing
SOURCE_EXTENSIONS = {
    ".cs", ".csproj", ".sln",          # C#
    ".py",                              # Python
    ".ts", ".tsx", ".js", ".jsx",       # TypeScript/JS
    ".html", ".css", ".scss",           # Web
    ".json", ".yaml", ".yml",           # Config
    ".sql",                             # Database
    ".md",                              # Docs
}

IGNORE_DIRS = {
    "node_modules", "bin", "obj", ".git", ".vscode",
    "dist", "__pycache__", ".next", "build", "venv",
    ".vs", "packages", "coverage",
}

MAX_FILE_SIZE_KB = 100


def index_project(project_path: str) -> dict:
    """
    Walk the project directory and build a lightweight index:
    {
      "files": [{"path": "...", "lang": "...", "size_kb": ...}],
      "structure": "tree string",
      "summary": "..."
    }
    """
    root = Path(project_path)
    files: list[dict] = []
    tree_lines: list[str] = []

    def _walk(directory: Path, prefix: str = "") -> None:
        try:
            entries = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except PermissionError:
            return

        for i, entry in enumerate(entries):
            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "
            extension = "    " if is_last else "│   "

            if entry.is_dir():
                if entry.name in IGNORE_DIRS:
                    continue
                tree_lines.append(f"{prefix}{connector}{entry.name}/")
                _walk(entry, prefix + extension)
            elif entry.is_file():
                if entry.suffix.lower() not in SOURCE_EXTENSIONS:
                    continue
                size_kb = entry.stat().st_size / 1024
                tree_lines.append(f"{prefix}{connector}{entry.name} ({size_kb:.1f}KB)")
                files.append({
                    "path": str(entry.relative_to(root)).replace("\\", "/"),
                    "abs_path": str(entry),
                    "lang": entry.suffix.lstrip("."),
                    "size_kb": round(size_kb, 1),
                })

    _walk(root)
    structure = "\n".join(tree_lines) or "(empty)"
    summary = f"{len(files)} source files, {sum(f['size_kb'] for f in files):.0f} KB total"

    return {"files": files, "structure": structure, "summary": summary}


def read_file(path: str, max_kb: float = MAX_FILE_SIZE_KB) -> str:
    """Read a file, truncating if too large."""
    try:
        p = Path(path)
        if p.stat().st_size / 1024 > max_kb:
            with open(p, encoding="utf-8", errors="replace") as f:
                content = f.read(int(max_kb * 1024))
            return content + "\n... [TRUNCATED]"
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def write_file(path: str, content: str) -> bool:
    """Write content to file, creating directories as needed."""
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return True
    except Exception:
        return False


def get_relevant_files(project_path: str, query: str, limit: int = 8) -> list[dict]:
    """
    Simple keyword-based file relevance: find files whose path or content
    contains keywords from the query.
    """
    index = index_project(project_path)
    keywords = set(query.lower().split())
    scored: list[tuple[int, dict]] = []

    for f in index["files"]:
        score = 0
        path_lower = f["path"].lower()
        for kw in keywords:
            if kw in path_lower:
                score += 2
        if score > 0 or f["size_kb"] < 20:
            content = read_file(f["abs_path"], max_kb=20)
            content_lower = content.lower()
            for kw in keywords:
                score += content_lower.count(kw)
            scored.append((score, {**f, "content_preview": content[:300]}))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:limit]]


def build_context_prompt(project_path: str, focus: str = "") -> str:
    """Build a concise context string for injection into agent prompts."""
    index = index_project(project_path)
    lines = [
        f"Project root: {project_path}",
        f"Structure:\n{index['structure']}",
    ]
    if focus:
        relevant = get_relevant_files(project_path, focus, limit=5)
        if relevant:
            lines.append("\nRelevant files:")
            for f in relevant:
                lines.append(f"\n// FILE: {f['path']}\n{read_file(f['abs_path'], max_kb=30)}")
    return "\n".join(lines)
