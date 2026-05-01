from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from herald_agent.errors import AgentError


@dataclass
class Runtime:
    config: dict[str, Any]
    workspace: Path


def within_workspace(workspace: Path, user_path: str | Path = ".") -> Path:
    path = Path(user_path)
    if not path.is_absolute():
        path = workspace / path
    resolved = path.resolve()
    try:
        resolved.relative_to(workspace)
    except ValueError as exc:
        raise AgentError(f"Path escapes workspace: {user_path}") from exc
    return resolved
