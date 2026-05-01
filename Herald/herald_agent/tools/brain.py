from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from herald_agent.brain import (
    brain_directory,
    build_graph,
    ensure_brain_directory,
    ensure_brain_enabled,
    extract_links,
    note_relpath,
    note_summaries,
    note_title,
    refresh_brain_index,
    safe_note_path,
)
from herald_agent.config import config_bool, config_int
from herald_agent.errors import AgentError
from herald_agent.runtime import Runtime
from herald_agent.utils import truncate


def brain_list(runtime: Runtime, max_entries: int = 100) -> str:
    ensure_brain_enabled(runtime)
    ensure_brain_directory(runtime)
    summaries = note_summaries(runtime)[: max(1, int(max_entries))]
    return json.dumps({"directory": str(brain_directory(runtime).relative_to(runtime.workspace)), "notes": summaries}, ensure_ascii=False, indent=2)


def brain_read(runtime: Runtime, path: str, max_chars: int = 12000) -> str:
    ensure_brain_enabled(runtime)
    target = safe_note_path(runtime, path)
    if not target.is_file():
        raise AgentError(f"Brain note does not exist: {path}")
    max_note_chars = config_int(runtime.config, "brain", "max_note_chars", default=20000)
    content = target.read_text(encoding="utf-8", errors="replace")
    root = brain_directory(runtime)
    rel = note_relpath(root, target)
    links, backlinks, _ = build_graph(runtime)
    payload: dict[str, Any] = {
        "path": rel,
        "title": note_title(content, Path(rel).stem),
        "links": links.get(rel, extract_links(content)),
        "backlinks": backlinks.get(rel, []),
        "content": truncate(content, min(int(max_chars), max_note_chars)),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def brain_write(runtime: Runtime, path: str, content: str) -> str:
    ensure_brain_enabled(runtime)
    if not config_bool(runtime.config, "brain", "allow_write", default=True):
        raise AgentError("Brain writes are disabled by config.")
    target = safe_note_path(runtime, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = str(content).rstrip() + "\n"
    target.write_text(text, encoding="utf-8")
    refresh_brain_index(runtime)
    rel = note_relpath(brain_directory(runtime), target)
    return f"Wrote {len(text)} chars to brain note {rel}"


def brain_append(runtime: Runtime, path: str, content: str) -> str:
    ensure_brain_enabled(runtime)
    if not config_bool(runtime.config, "brain", "allow_write", default=True):
        raise AgentError("Brain writes are disabled by config.")
    target = safe_note_path(runtime, path)
    target.parent.mkdir(parents=True, exist_ok=True)
    text = str(content)
    if target.exists() and target.stat().st_size > 0 and not text.startswith("\n"):
        text = "\n" + text
    if not text.endswith("\n"):
        text += "\n"
    with target.open("a", encoding="utf-8") as file:
        file.write(text)
    refresh_brain_index(runtime)
    rel = note_relpath(brain_directory(runtime), target)
    return f"Appended {len(text)} chars to brain note {rel}"
