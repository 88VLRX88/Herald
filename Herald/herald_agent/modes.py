from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from herald_agent.errors import AgentError


DEFAULT_MODE = "coder"
DEFAULT_MODE_DIR = ".Herald/modes"
DEFAULT_MODE_DIRS = (DEFAULT_MODE_DIR,)
MODE_SUFFIXES = {".md", ".txt"}
FRONT_MATTER_DELIMITER = "---"
TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


DEFAULT_MODE_FILES: dict[str, str] = {
    "coder.md": """
---
id: coder
label: coder
aliases: code, coding, dev, developer, кодер, программист, разработчик
description: Pragmatic coding agent for local project changes, focused implementation, and verification.
---

Act as a pragmatic coding agent. Inspect the local project before editing,
make focused changes, verify them with the narrowest useful checks, and keep
answers concise and implementation-oriented.
""",
    "philosopher.md": """
---
id: philosopher
label: philosopher(psychologist)
aliases: philosopher, philosopher-psychologist, philosophy, psychologist, psychology, psych, философ, психолог, философ(психолог), философ-психолог
description: Reflective philosophy and psychology-oriented assistant for ideas, values, motives, emotions, and choices.
---

Act as a reflective philosophy and psychology-oriented assistant. Help the
user examine ideas, values, motives, emotions, and choices with careful
questions and grounded reasoning. Do not diagnose medical or mental-health
conditions, and recommend professional or emergency help when safety is at risk.
""",
    "mathematician.md": """
---
id: mathematician
label: mathematician
aliases: math, mathematics, математик, математика
description: Careful mathematician for assumptions, definitions, derivations, edge cases, and exact results.
---

Act as a careful mathematician. State assumptions, define terms when useful,
show the derivation clearly, check edge cases, and separate exact results from
approximations.
""",
    "research.md": """
---
id: research
label: research
aliases: researcher, search, web, исследователь, ресерч, поиск
description: Research assistant that uses web search for current or external facts and compares sources.
---

Act as a research assistant. Use web_search for current or external facts,
compare multiple results when accuracy matters, name sources in the final answer,
and save durable findings to brain notes when brain memory is enabled.
""",
    "assist.md": """
---
id: assist
label: assist
aliases: assistant, helper, system, ассист, ассистент, помощник, система
description: System work assistant that can use all available tools for filesystem, commands, web search, and memory.
---

Act as a system work assistant. You may use all available tool calls when they
help: filesystem, command execution, Python snippets, web search, and brain
memory. Inspect state before changing it, avoid destructive actions unless
clearly requested, and report the concrete result of tool-backed work.
""",
}


@dataclass(frozen=True)
class AgentMode:
    id: str
    label: str
    instructions: str
    aliases: tuple[str, ...] = ()
    description: str = ""
    source: str = "mode document"


@dataclass(frozen=True)
class ModeRegistry:
    modes: dict[str, AgentMode]
    aliases: dict[str, str]


def normalize_mode_key(value: str | None) -> str:
    key = (value or "").strip().lower().replace("_", "-")
    key = re.sub(r"\s+", "-", key)
    key = re.sub(r"-{2,}", "-", key)
    return key.strip("-")


def tokenize(value: str) -> set[str]:
    return {match.group(0).lower() for match in TOKEN_RE.finditer(value)}


def normalize_mode(
    value: str | None,
    config: dict[str, Any] | None = None,
    workspace: Path | None = None,
) -> str:
    registry = build_mode_registry(config, workspace)
    return normalize_mode_in_registry(value, registry)


def normalize_mode_in_registry(value: str | None, registry: ModeRegistry) -> str:
    if not value:
        return DEFAULT_MODE

    key = normalize_mode_key(value)
    normalized = registry.aliases.get(key, key)
    if normalized in registry.modes:
        return normalized

    retrieved = retrieve_mode_id(value, registry)
    if retrieved:
        return retrieved

    raise AgentError(f"Unknown agent mode: {value}. Available modes: {mode_choices_from_registry(registry)}")


def get_mode(config: dict[str, Any], workspace: Path | None = None) -> AgentMode:
    agent = config.get("agent", {})
    raw_mode = agent.get("mode") if isinstance(agent, dict) else None
    registry = build_mode_registry(config, workspace)
    mode_id = normalize_mode_in_registry(raw_mode, registry)
    return registry.modes[mode_id]


def set_mode(config: dict[str, Any], value: str, workspace: Path | None = None) -> AgentMode:
    registry = build_mode_registry(config, workspace)
    mode_id = normalize_mode_in_registry(value, registry)
    agent = config.setdefault("agent", {})
    if not isinstance(agent, dict):
        agent = {}
        config["agent"] = agent
    agent["mode"] = mode_id
    return registry.modes[mode_id]


def mode_choices_text(config: dict[str, Any] | None = None, workspace: Path | None = None) -> str:
    registry = build_mode_registry(config, workspace)
    return mode_choices_from_registry(registry)


def mode_choices_from_registry(registry: ModeRegistry) -> str:
    return ", ".join(registry.modes)


def build_mode_registry(config: dict[str, Any] | None = None, workspace: Path | None = None) -> ModeRegistry:
    if workspace is None:
        return build_default_template_registry()

    ensure_default_mode_files(config, workspace)

    modes: dict[str, AgentMode] = {}
    aliases: dict[str, str] = {}
    for mode in load_mode_documents(config, workspace):
        register_mode(modes, aliases, mode)
    return ModeRegistry(modes=modes, aliases=aliases)


def build_default_template_registry() -> ModeRegistry:
    modes: dict[str, AgentMode] = {}
    aliases: dict[str, str] = {}
    for filename, content in DEFAULT_MODE_FILES.items():
        mode = parse_mode_content(content, source=f"{DEFAULT_MODE_DIR}/{filename}")
        register_mode(modes, aliases, mode)
    return ModeRegistry(modes=modes, aliases=aliases)


def register_mode(modes: dict[str, AgentMode], aliases: dict[str, str], mode: AgentMode) -> None:
    if mode.id in modes:
        raise AgentError(f"Mode document {mode.source} duplicates existing mode id {mode.id!r}.")

    candidate_aliases = {mode.id, mode.label, *mode.aliases}
    for alias in candidate_aliases:
        key = normalize_mode_key(alias)
        if not key:
            continue
        existing = aliases.get(key)
        if existing and existing != mode.id:
            raise AgentError(
                f"Mode document {mode.source} uses alias {alias!r}, "
                f"already assigned to mode {existing!r}."
            )

    modes[mode.id] = mode
    for alias in candidate_aliases:
        key = normalize_mode_key(alias)
        if key:
            aliases[key] = mode.id


def ensure_default_mode_files(config: dict[str, Any] | None, workspace: Path) -> None:
    target_dir = mode_dirs(config, workspace)[0]
    target_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in DEFAULT_MODE_FILES.items():
        path = target_dir / filename
        if not path.exists():
            path.write_text(content.strip() + "\n", encoding="utf-8")


def load_mode_documents(config: dict[str, Any] | None, workspace: Path) -> list[AgentMode]:
    modes: list[AgentMode] = []
    for mode_dir in mode_dirs(config, workspace):
        if not mode_dir.exists():
            continue
        if not mode_dir.is_dir():
            raise AgentError(f"Mode path is not a directory: {mode_dir}")
        for path in sorted(mode_dir.rglob("*"), key=lambda item: item.as_posix().lower()):
            if path.is_file() and path.suffix.lower() in MODE_SUFFIXES:
                modes.append(parse_mode_file(path, workspace))
    return modes


def mode_dirs(config: dict[str, Any] | None, workspace: Path) -> list[Path]:
    agent = config.get("agent", {}) if isinstance(config, dict) else {}
    if not isinstance(agent, dict):
        agent = {}

    raw_dirs = agent.get("mode_dirs", agent.get("custom_mode_dirs", DEFAULT_MODE_DIRS))
    if isinstance(raw_dirs, str):
        raw_items: list[Any] = [raw_dirs]
    elif isinstance(raw_dirs, (list, tuple)):
        raw_items = raw_dirs
    else:
        raise AgentError("agent.mode_dirs must be a string or a list of strings.")

    resolved: list[Path] = []
    workspace = workspace.resolve()
    for raw in raw_items:
        raw_text = str(raw).strip()
        if not raw_text:
            continue
        path = Path(raw_text)
        if not path.is_absolute():
            path = workspace / path
        path = path.resolve()
        try:
            path.relative_to(workspace)
        except ValueError as exc:
            raise AgentError(f"Mode directory escapes workspace: {raw_text}") from exc
        resolved.append(path)

    if not resolved:
        raise AgentError("agent.mode_dirs must contain at least one directory.")
    return resolved


def parse_mode_file(path: Path, workspace: Path) -> AgentMode:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise AgentError(f"Could not read mode file {path}: {exc}") from exc

    return parse_mode_content(content, source=source_label(path, workspace), fallback_id=path.stem)


def parse_mode_content(content: str, *, source: str, fallback_id: str = "") -> AgentMode:
    metadata, body = split_mode_file(content.lstrip())
    body = body.strip()
    if not body:
        raise AgentError(f"Mode document {source} has no instruction body.")

    raw_id = string_metadata(metadata, "id") or fallback_id
    mode_id = normalize_mode_key(raw_id)
    if not mode_id:
        raise AgentError(f"Mode document {source} has an empty id.")
    if "/" in mode_id or "\\" in mode_id:
        raise AgentError(f"Mode document {source} has an invalid id: {raw_id!r}")

    label = string_metadata(metadata, "label") or markdown_title(body) or mode_id
    description = string_metadata(metadata, "description")
    aliases = tuple(metadata_list(metadata, "aliases"))

    return AgentMode(
        id=mode_id,
        label=label.strip(),
        instructions=body,
        aliases=aliases,
        description=description,
        source=source,
    )


def split_mode_file(content: str) -> tuple[dict[str, Any], str]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != FRONT_MATTER_DELIMITER:
        return {}, content

    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == FRONT_MATTER_DELIMITER:
            metadata = parse_front_matter(lines[1:index])
            body = "\n".join(lines[index + 1 :])
            return metadata, body
    raise AgentError("Mode front matter is opened with --- but never closed.")


def parse_front_matter(lines: list[str]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    current_list_key: str | None = None
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if current_list_key and stripped.startswith("- "):
            metadata.setdefault(current_list_key, []).append(clean_scalar(stripped[2:]))
            continue

        current_list_key = None
        if ":" not in line:
            raise AgentError(f"Invalid mode metadata line: {line}")

        key, raw_value = line.split(":", 1)
        key = key.strip().lower().replace("-", "_")
        value = raw_value.strip()
        if not key:
            raise AgentError(f"Invalid mode metadata line: {line}")
        if value == "":
            metadata[key] = []
            current_list_key = key
        else:
            metadata[key] = parse_metadata_value(value)
    return metadata


def parse_metadata_value(value: str) -> str | list[str]:
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [clean_scalar(item) for item in inner.split(",") if clean_scalar(item)]
    return clean_scalar(value)


def clean_scalar(value: str) -> str:
    return value.strip().strip("\"'")


def string_metadata(metadata: dict[str, Any], key: str) -> str:
    value = metadata.get(key)
    if isinstance(value, str):
        return value.strip()
    return ""


def metadata_list(metadata: dict[str, Any], key: str) -> list[str]:
    value = metadata.get(key)
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def markdown_title(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return ""


def source_label(path: Path, workspace: Path) -> str:
    try:
        return path.resolve().relative_to(workspace.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def retrieve_mode_id(query: str, registry: ModeRegistry) -> str | None:
    query_tokens = tokenize(query)
    if not query_tokens:
        return None

    best_id: str | None = None
    best_score = 0
    tied = False
    query_key = normalize_mode_key(query)
    for mode_id, mode in registry.modes.items():
        metadata_text = " ".join([mode.id, mode.label, mode.description, *mode.aliases])
        metadata_key = normalize_mode_key(metadata_text)
        metadata_tokens = tokenize(metadata_text)
        instruction_tokens = tokenize(mode.instructions[:4000])

        score = 0
        if query_key and query_key in metadata_key:
            score += 20
        score += 5 * len(query_tokens & metadata_tokens)
        score += min(5, len(query_tokens & instruction_tokens))

        if score > best_score:
            best_id = mode_id
            best_score = score
            tied = False
        elif score == best_score and score > 0:
            tied = True

    if tied:
        return None
    return best_id if best_score >= retrieval_threshold(query_tokens) else None


def retrieval_threshold(query_tokens: set[str]) -> int:
    if len(query_tokens) <= 1:
        return 5
    return min(10, len(query_tokens) * 3)
