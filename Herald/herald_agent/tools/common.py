from __future__ import annotations

from typing import Any

from herald_agent.config import config_bool
from herald_agent.errors import AgentError


def ensure_tool_enabled(config: dict[str, Any], category: str) -> None:
    if not config_bool(config, "tools", category, "enabled", default=True):
        raise AgentError(f"Tool category is disabled: {category}")
