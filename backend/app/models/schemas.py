from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any
from enum import Enum


class AgentName(str, Enum):
    ARCHITECT = "architect"
    BACKEND = "backend"
    FRONTEND = "frontend"
    DATABASE = "database"
    DEBUG = "debug"
    TEST = "test"
    DOCUMENTATION = "documentation"
    GIT = "git"


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    SKIPPED = "skipped"


class EventType(str, Enum):
    AGENT_START = "agent_start"
    AGENT_DONE = "agent_done"
    AGENT_ERROR = "agent_error"
    LOG = "log"
    FILE_CREATED = "file_created"
    FILE_MODIFIED = "file_modified"
    COMMAND_RUN = "command_run"
    COMMAND_OUTPUT = "command_output"
    MEMORY_UPDATE = "memory_update"
    BUILD_SUCCESS = "build_success"
    BUILD_ERROR = "build_error"
    FORGE_COMPLETE = "forge_complete"
    FORGE_ERROR = "forge_error"


# ── Requests ──────────────────────────────────────────────────────────────────

class ForgeRequest(BaseModel):
    prompt: str
    project_path: str
    rules: list[str] = []
    tech_stack: dict[str, str] = {}
    agents_enabled: list[AgentName] = list(AgentName)
    models_override: dict[str, str] = {}


class DebugRequest(BaseModel):
    project_path: str
    error_output: str
    command: str = "dotnet build"


class EvolutionRequest(BaseModel):
    project_path: str
    checks: list[str] = []


class AddRuleRequest(BaseModel):
    project_path: str
    rule: str


class ChatRequest(BaseModel):
    project_path: str
    message: str
    agent: AgentName = AgentName.BACKEND


# ── Responses ─────────────────────────────────────────────────────────────────

class SSEEvent(BaseModel):
    type: EventType
    agent: str | None = None
    message: str = ""
    data: dict[str, Any] = {}


class ProjectMemoryResponse(BaseModel):
    project_name: str
    description: str
    tech_stack: dict[str, str]
    architecture: str
    decisions: list[str]
    rules: list[str]
    todo: list[str]
    files_created: list[str]
    created_at: str
    updated_at: str


class OllamaModel(BaseModel):
    name: str
    size_gb: float = 0.0
    family: str = ""


class StatusResponse(BaseModel):
    status: str
    ollama_online: bool
    models: list[OllamaModel]
    active_models: dict[str, str]
    version: str = "1.0.0"
