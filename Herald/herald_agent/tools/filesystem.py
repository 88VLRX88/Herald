from __future__ import annotations

import json
from typing import Any

from herald_agent.config import config_bool, config_int
from herald_agent.errors import AgentError
from herald_agent.runtime import Runtime, within_workspace
from herald_agent.tools.common import ensure_tool_enabled
from herald_agent.utils import truncate


def fs_list(runtime: Runtime, path: str = ".") -> str:
    ensure_tool_enabled(runtime.config, "filesystem")
    target = within_workspace(runtime.workspace, path)
    if not target.exists():
        raise AgentError(f"Path does not exist: {path}")
    if target.is_file():
        stat = target.stat()
        return json.dumps(
            [{"path": str(target.relative_to(runtime.workspace)), "type": "file", "bytes": stat.st_size}],
            ensure_ascii=False,
        )

    entries: list[dict[str, Any]] = []
    max_entries = config_int(runtime.config, "tools", "filesystem", "max_list_entries", default=200)
    for child in sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))[:max_entries]:
        stat = child.stat()
        entries.append(
            {
                "path": str(child.relative_to(runtime.workspace)),
                "type": "dir" if child.is_dir() else "file",
                "bytes": stat.st_size,
            }
        )
    return json.dumps(entries, ensure_ascii=False, indent=2)


def fs_read(runtime: Runtime, path: str, max_chars: int = 12000) -> str:
    ensure_tool_enabled(runtime.config, "filesystem")
    target = within_workspace(runtime.workspace, path)
    if not target.is_file():
        raise AgentError(f"Not a file: {path}")
    max_file_bytes = config_int(runtime.config, "tools", "filesystem", "max_read_bytes", default=1_000_000)
    if target.stat().st_size > max_file_bytes:
        raise AgentError(f"File is too large: {path}")
    content = target.read_text(encoding="utf-8", errors="replace")
    return truncate(content, int(max_chars))


def fs_write(runtime: Runtime, path: str, content: str) -> str:
    ensure_tool_enabled(runtime.config, "filesystem")
    if not config_bool(runtime.config, "tools", "filesystem", "allow_write", default=True):
        raise AgentError("File writes are disabled by config.")
    target = within_workspace(runtime.workspace, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} chars to {target.relative_to(runtime.workspace)}"


def fs_append(runtime: Runtime, path: str, content: str) -> str:
    ensure_tool_enabled(runtime.config, "filesystem")
    if not config_bool(runtime.config, "tools", "filesystem", "allow_write", default=True):
        raise AgentError("File writes are disabled by config.")
    target = within_workspace(runtime.workspace, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as file:
        file.write(content)
    return f"Appended {len(content)} chars to {target.relative_to(runtime.workspace)}"


def fs_mkdir(runtime: Runtime, path: str) -> str:
    ensure_tool_enabled(runtime.config, "filesystem")
    if not config_bool(runtime.config, "tools", "filesystem", "allow_write", default=True):
        raise AgentError("Directory writes are disabled by config.")
    target = within_workspace(runtime.workspace, path)
    target.mkdir(parents=True, exist_ok=True)
    return f"Created directory {target.relative_to(runtime.workspace)}"


def fs_delete(runtime: Runtime, path: str) -> str:
    ensure_tool_enabled(runtime.config, "filesystem")
    if not config_bool(runtime.config, "tools", "filesystem", "allow_delete", default=False):
        raise AgentError("Delete is disabled by config.")
    target = within_workspace(runtime.workspace, path)
    if target.is_dir():
        target.rmdir()
        return f"Deleted empty directory {target.relative_to(runtime.workspace)}"
    if target.is_file():
        target.unlink()
        return f"Deleted file {target.relative_to(runtime.workspace)}"
    raise AgentError(f"Path does not exist: {path}")
