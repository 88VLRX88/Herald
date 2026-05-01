from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from herald_agent.config import config_bool, config_int
from herald_agent.errors import AgentError
from herald_agent.runtime import Runtime, within_workspace
from herald_agent.utils import truncate


DEFAULT_BRAIN_DIR = ".Herald"
DEFAULT_INDEX_FILE = "index.md"
TEXT_SUFFIXES = {".md", ".txt"}
WIKI_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")


def brain_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.setdefault("brain", {})
    if not isinstance(raw, dict):
        raw = {}
        config["brain"] = raw
    raw.setdefault("enabled", True)
    raw.setdefault("directory", DEFAULT_BRAIN_DIR)
    raw.setdefault("index_file", DEFAULT_INDEX_FILE)
    raw.setdefault("max_note_chars", 20000)
    raw.setdefault("max_list_entries", 100)
    return raw


def is_brain_enabled(config: dict[str, Any]) -> bool:
    return config_bool(config, "brain", "enabled", default=True)


def set_brain_enabled(config: dict[str, Any], enabled: bool) -> None:
    brain_config(config)["enabled"] = enabled


def brain_directory(runtime: Runtime) -> Path:
    raw_dir = str(brain_config(runtime.config).get("directory") or DEFAULT_BRAIN_DIR)
    return within_workspace(runtime.workspace, raw_dir)


def brain_index_name(config: dict[str, Any]) -> str:
    raw = str(brain_config(config).get("index_file") or DEFAULT_INDEX_FILE).strip()
    if not raw:
        return DEFAULT_INDEX_FILE
    if Path(raw).name != raw:
        raise AgentError("Brain index_file must be a file name, not a path.")
    if Path(raw).suffix.lower() not in TEXT_SUFFIXES:
        raise AgentError("Brain index_file must be a .md or .txt file.")
    return raw


def ensure_brain_enabled(runtime: Runtime) -> None:
    if not is_brain_enabled(runtime.config):
        raise AgentError("Brain is disabled. Use /brain on to enable it in chat.")


def ensure_brain_directory(runtime: Runtime) -> Path:
    root = brain_directory(runtime)
    root.mkdir(parents=True, exist_ok=True)
    index_path = root / brain_index_name(runtime.config)
    if not index_path.exists():
        index_path.write_text(initial_index_text(), encoding="utf-8")
    return root


def initial_index_text() -> str:
    return (
        "# Herald Brain\n\n"
        "This index is maintained by Herald brain tools.\n\n"
        "Use `[[note-name]]` or Markdown links to connect notes.\n"
    )


def safe_note_path(runtime: Runtime, path: str) -> Path:
    root = ensure_brain_directory(runtime)
    raw = (path or "").strip()
    if not raw:
        raw = DEFAULT_INDEX_FILE
    candidate = Path(raw)
    if candidate.is_absolute():
        raise AgentError("Brain note paths must be relative.")
    if candidate.suffix == "":
        candidate = candidate.with_suffix(".md")
    if candidate.suffix.lower() not in TEXT_SUFFIXES:
        raise AgentError("Brain notes must be .md or .txt files.")

    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise AgentError(f"Brain path escapes {DEFAULT_BRAIN_DIR}: {path}") from exc
    return resolved


def note_relpath(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def list_note_paths(runtime: Runtime, *, include_index: bool = False) -> list[Path]:
    root = ensure_brain_directory(runtime)
    index_name = brain_index_name(runtime.config)
    limit = config_int(runtime.config, "brain", "max_list_entries", default=100)
    notes = [
        path
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in TEXT_SUFFIXES
        and (include_index or note_relpath(root, path) != index_name)
    ]
    return sorted(notes, key=lambda item: note_relpath(root, item).lower())[:limit]


def note_title(content: str, fallback: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or fallback
    return fallback


def normalize_note_reference(raw: str) -> str | None:
    value = raw.strip()
    if "|" in value:
        value = value.split("|", 1)[0].strip()
    if "#" in value:
        value = value.split("#", 1)[0].strip()
    value = value.replace("\\", "/").lstrip("./")
    if not value or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", value):
        return None
    candidate = Path(value)
    if candidate.suffix == "":
        candidate = candidate.with_suffix(".md")
    if candidate.suffix.lower() not in TEXT_SUFFIXES:
        return None
    return candidate.as_posix()


def extract_links(content: str) -> list[str]:
    links: set[str] = set()
    for match in WIKI_LINK_RE.finditer(content):
        link = normalize_note_reference(match.group(1))
        if link:
            links.add(link)
    for match in MARKDOWN_LINK_RE.finditer(content):
        link = normalize_note_reference(match.group(1))
        if link:
            links.add(link)
    return sorted(links)


def build_graph(runtime: Runtime) -> tuple[dict[str, list[str]], dict[str, list[str]], dict[str, str]]:
    root = ensure_brain_directory(runtime)
    note_paths = list_note_paths(runtime, include_index=False)
    existing = {note_relpath(root, path) for path in note_paths}
    links: dict[str, list[str]] = {}
    titles: dict[str, str] = {}
    backlinks: dict[str, list[str]] = {rel: [] for rel in existing}

    for path in note_paths:
        rel = note_relpath(root, path)
        content = path.read_text(encoding="utf-8", errors="replace")
        titles[rel] = note_title(content, Path(rel).stem)
        note_links = [link for link in extract_links(content) if link in existing and link != rel]
        links[rel] = note_links
        for link in note_links:
            backlinks.setdefault(link, []).append(rel)

    for rel in backlinks:
        backlinks[rel] = sorted(set(backlinks[rel]))
    return links, backlinks, titles


def note_summaries(runtime: Runtime) -> list[dict[str, Any]]:
    root = ensure_brain_directory(runtime)
    links, backlinks, titles = build_graph(runtime)
    summaries: list[dict[str, Any]] = []
    for path in list_note_paths(runtime, include_index=False):
        rel = note_relpath(root, path)
        content = path.read_text(encoding="utf-8", errors="replace")
        summaries.append(
            {
                "path": rel,
                "title": titles.get(rel, Path(rel).stem),
                "bytes": path.stat().st_size,
                "links": links.get(rel, []),
                "backlinks": backlinks.get(rel, []),
                "preview": truncate(content.replace("\n", " "), 180),
            }
        )
    return summaries


def refresh_brain_index(runtime: Runtime) -> None:
    root = ensure_brain_directory(runtime)
    index_name = brain_index_name(runtime.config)
    index_path = root / index_name
    links, backlinks, titles = build_graph(runtime)

    lines = [
        "# Herald Brain",
        "",
        "Generated by Herald brain tools. Note files use `[[note-name]]` or Markdown links.",
        "",
        "## Notes",
    ]
    if not titles:
        lines.append("")
        lines.append("No notes yet.")
    for rel in sorted(titles, key=str.lower):
        lines.append(f"- [[{Path(rel).with_suffix('').as_posix()}]] - {titles[rel]}")
        if links.get(rel):
            linked = ", ".join(f"[[{Path(item).with_suffix('').as_posix()}]]" for item in links[rel])
            lines.append(f"  - links: {linked}")
        if backlinks.get(rel):
            linked = ", ".join(f"[[{Path(item).with_suffix('').as_posix()}]]" for item in backlinks[rel])
            lines.append(f"  - backlinks: {linked}")
    index_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
