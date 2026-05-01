from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from herald_agent.errors import AgentError


DEFAULT_CONFIG = "agent_config.json"


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise AgentError(f"Config file not found: {path}")
    with path.open("r", encoding="utf-8") as file:
        config = json.load(file)

    llm = config.setdefault("llm", {})
    llm["api_token"] = env_or_value(llm.get("api_token_env"), llm.get("api_token", ""))

    web = config.setdefault("tools", {}).setdefault("websearch", {})
    web["api_token"] = env_or_value(web.get("api_token_env"), web.get("api_token", ""))
    return config


def env_or_value(env_name: str | None, value: str) -> str:
    if env_name and os.getenv(env_name):
        return os.environ[env_name]
    return value


def resolve_workspace(config: dict[str, Any], config_path: Path) -> Path:
    raw_workspace = config.get("workspace", ".")
    workspace = Path(raw_workspace)
    if not workspace.is_absolute():
        workspace = config_path.parent / workspace
    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def config_bool(config: dict[str, Any], *path: str, default: bool = False) -> bool:
    node: Any = config
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return bool(node)


def config_int(config: dict[str, Any], *path: str, default: int) -> int:
    node: Any = config
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    try:
        return int(node)
    except (TypeError, ValueError):
        return default


def response_format_json(config: dict[str, Any]) -> bool:
    llm = config.get("llm", {})
    return bool(llm.get("response_format_json", True))
