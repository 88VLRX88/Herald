from __future__ import annotations

from typing import Any, Callable

from herald_agent.errors import AgentError
from herald_agent.plugins import execute_plugin_tool, get_plugin_registry
from herald_agent.runtime import Runtime
from herald_agent.tools.brain import brain_append, brain_list, brain_read, brain_write
from herald_agent.tools.execute import run_command, run_python
from herald_agent.tools.filesystem import fs_append, fs_delete, fs_list, fs_mkdir, fs_read, fs_write
from herald_agent.tools.websearch import web_search


Tool = Callable[..., str]


TOOLS: dict[str, Tool] = {
    "fs_list": fs_list,
    "fs_read": fs_read,
    "fs_write": fs_write,
    "fs_append": fs_append,
    "fs_mkdir": fs_mkdir,
    "fs_delete": fs_delete,
    "run_command": run_command,
    "run_python": run_python,
    "web_search": web_search,
    "brain_list": brain_list,
    "brain_read": brain_read,
    "brain_write": brain_write,
    "brain_append": brain_append,
}


def execute_tool(action: dict[str, Any], runtime: Runtime) -> str:
    tool = action.get("tool")
    args = action.get("args") or {}
    if not isinstance(args, dict):
        raise AgentError("Tool args must be an object.")
    if tool in TOOLS:
        return TOOLS[tool](runtime, **args)

    plugin_registry = get_plugin_registry(runtime.config, runtime.workspace)
    if tool in plugin_registry.tools:
        return execute_plugin_tool(runtime, str(tool), args)
    raise AgentError(f"Unknown tool: {tool}")
