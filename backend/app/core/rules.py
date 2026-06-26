from __future__ import annotations
from . import memory

# Built-in rule templates users can reference by name
RULE_TEMPLATES: dict[str, str] = {
    "clean-architecture": "Always follow Clean Architecture: Domain → Application → Infrastructure → Presentation layers. No cross-layer dependencies.",
    "repository-pattern": "Always use the Repository Pattern for data access. Never access DbContext directly from controllers.",
    "fluent-validation": "Always use FluentValidation for all input validation. Never use DataAnnotations.",
    "solid": "Strictly follow SOLID principles. Each class has one responsibility.",
    "async-all": "All database and I/O operations must be async/await. No blocking calls.",
    "no-magic-strings": "No magic strings. Use constants, enums, or configuration.",
    "error-handling": "Every controller endpoint must have try/catch and return ProblemDetails on error.",
    "cqrs": "Use CQRS pattern: separate Command and Query handlers via MediatR.",
    "ddd": "Apply Domain-Driven Design: Aggregates, Value Objects, Domain Events.",
    "dto-mapping": "Never return domain entities from API endpoints. Always use DTOs with AutoMapper.",
}


def resolve_rules(rules: list[str]) -> list[str]:
    """
    Expand rule names to their full text.
    Rules starting with known templates are expanded; others are kept as-is.
    """
    expanded: list[str] = []
    for rule in rules:
        key = rule.strip().lower().replace(" ", "-")
        if key in RULE_TEMPLATES:
            expanded.append(RULE_TEMPLATES[key])
        else:
            expanded.append(rule)
    return expanded


def format_rules_for_prompt(rules: list[str]) -> str:
    """Format rules list for injection into agent system prompts."""
    if not rules:
        return ""
    resolved = resolve_rules(rules)
    lines = ["MANDATORY CODING RULES (you MUST follow all of these):"]
    for i, rule in enumerate(resolved, 1):
        lines.append(f"{i}. {rule}")
    return "\n".join(lines)


async def get_project_rules(project_path: str) -> list[str]:
    mem = await memory.load(project_path)
    return mem.get("rules", []) if mem else []


async def get_rules_prompt(project_path: str, extra_rules: list[str] | None = None) -> str:
    rules = await get_project_rules(project_path)
    if extra_rules:
        rules = rules + extra_rules
    return format_rules_for_prompt(rules)
