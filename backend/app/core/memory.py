from __future__ import annotations
import aiosqlite
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parents[3] / "autoforge_memory.db"


async def _db() -> aiosqlite.Connection:
    conn = await aiosqlite.connect(DB_PATH)
    conn.row_factory = aiosqlite.Row
    return conn


async def init_db() -> None:
    async with await _db() as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                path        TEXT PRIMARY KEY,
                name        TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                tech_stack  TEXT NOT NULL DEFAULT '{}',
                architecture TEXT NOT NULL DEFAULT '',
                decisions   TEXT NOT NULL DEFAULT '[]',
                rules       TEXT NOT NULL DEFAULT '[]',
                todo        TEXT NOT NULL DEFAULT '[]',
                files       TEXT NOT NULL DEFAULT '[]',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                project_path TEXT NOT NULL,
                agent       TEXT NOT NULL,
                type        TEXT NOT NULL,
                message     TEXT NOT NULL,
                ts          TEXT NOT NULL
            );
        """)
        await db.commit()


async def load(project_path: str) -> dict:
    async with await _db() as db:
        cur = await db.execute("SELECT * FROM projects WHERE path=?", (project_path,))
        row = await cur.fetchone()
        if not row:
            return {}
        return {
            "path": row["path"],
            "name": row["name"],
            "description": row["description"],
            "tech_stack": json.loads(row["tech_stack"]),
            "architecture": row["architecture"],
            "decisions": json.loads(row["decisions"]),
            "rules": json.loads(row["rules"]),
            "todo": json.loads(row["todo"]),
            "files": json.loads(row["files"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


async def save(project_path: str, data: dict) -> None:
    now = datetime.utcnow().isoformat()
    existing = await load(project_path)

    async with await _db() as db:
        if not existing:
            await db.execute("""
                INSERT INTO projects
                (path, name, description, tech_stack, architecture, decisions, rules, todo, files, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                project_path,
                data.get("name", ""),
                data.get("description", ""),
                json.dumps(data.get("tech_stack", {})),
                data.get("architecture", ""),
                json.dumps(data.get("decisions", [])),
                json.dumps(data.get("rules", [])),
                json.dumps(data.get("todo", [])),
                json.dumps(data.get("files", [])),
                now, now
            ))
        else:
            await db.execute("""
                UPDATE projects SET
                  name=?, description=?, tech_stack=?, architecture=?,
                  decisions=?, rules=?, todo=?, files=?, updated_at=?
                WHERE path=?
            """, (
                data.get("name", existing.get("name", "")),
                data.get("description", existing.get("description", "")),
                json.dumps(data.get("tech_stack", existing.get("tech_stack", {}))),
                data.get("architecture", existing.get("architecture", "")),
                json.dumps(data.get("decisions", existing.get("decisions", []))),
                json.dumps(data.get("rules", existing.get("rules", []))),
                json.dumps(data.get("todo", existing.get("todo", []))),
                json.dumps(data.get("files", existing.get("files", []))),
                now, project_path
            ))
        await db.commit()


async def append_file(project_path: str, file_path: str) -> None:
    mem = await load(project_path)
    if not mem:
        return
    files: list[str] = mem.get("files", [])
    if file_path not in files:
        files.append(file_path)
        await save(project_path, {**mem, "files": files})


async def add_decision(project_path: str, decision: str) -> None:
    mem = await load(project_path)
    if not mem:
        return
    decisions: list[str] = mem.get("decisions", [])
    decisions.append(f"[{datetime.utcnow().strftime('%Y-%m-%d')}] {decision}")
    await save(project_path, {**mem, "decisions": decisions})


async def add_rule(project_path: str, rule: str) -> None:
    mem = await load(project_path)
    rules: list[str] = mem.get("rules", [])
    if rule not in rules:
        rules.append(rule)
        await save(project_path, {**mem, "rules": rules})


async def log_event(project_path: str, agent: str, event_type: str, message: str) -> None:
    async with await _db() as db:
        await db.execute(
            "INSERT INTO events (project_path, agent, type, message, ts) VALUES (?, ?, ?, ?, ?)",
            (project_path, agent, event_type, message, datetime.utcnow().isoformat())
        )
        await db.commit()


async def get_events(project_path: str, limit: int = 100) -> list[dict]:
    async with await _db() as db:
        cur = await db.execute(
            "SELECT * FROM events WHERE project_path=? ORDER BY id DESC LIMIT ?",
            (project_path, limit)
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]
