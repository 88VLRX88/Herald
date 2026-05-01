from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

from herald_agent.config import config_bool
from herald_agent.errors import AgentError
from herald_agent.protocol import TOOL_NAMES as BUILTIN_TOOL_NAMES
from herald_agent.runtime import within_workspace


DEFAULT_PLUGIN_DIRS = ("plugins",)
DEFAULT_PLUGIN_DATA_DIR = ".Herald/plugin-data"
PLUGIN_MANIFEST = "plugin.json"
DEFAULT_ENTRYPOINT = "plugin.py"
IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


PluginCallable = Callable[..., Any]


@dataclass(frozen=True)
class PluginInfo:
    id: str
    name: str
    description: str
    instructions: str
    plugin_dir: Path
    entrypoint: Path
    config: dict[str, Any]


@dataclass(frozen=True)
class PluginTool:
    name: str
    description: str
    plugin: PluginInfo
    function: PluginCallable


@dataclass(frozen=True)
class PluginRegistry:
    plugins: tuple[PluginInfo, ...]
    tools: dict[str, PluginTool]


@dataclass(frozen=True)
class PluginContext:
    plugin_id: str
    workspace: Path
    plugin_dir: Path
    data_dir: Path
    config: dict[str, Any]
    agent_config: dict[str, Any]

    def workspace_path(self, path: str | Path = ".") -> Path:
        return within_workspace(self.workspace, path)

    def plugin_path(self, path: str | Path = ".") -> Path:
        return path_within(self.plugin_dir, path, "Plugin path escapes plugin directory")

    def data_path(self, path: str | Path = ".") -> Path:
        return path_within(self.data_dir, path, "Plugin data path escapes plugin data directory")


_REGISTRY_CACHE: dict[tuple[Any, ...], PluginRegistry] = {}


def get_plugin_registry(config: dict[str, Any], workspace: Path) -> PluginRegistry:
    if not plugins_enabled(config):
        return PluginRegistry(plugins=(), tools={})
    key = plugin_cache_key(config, workspace)
    cached = _REGISTRY_CACHE.get(key)
    if cached:
        return cached
    registry = load_plugin_registry(config, workspace)
    _REGISTRY_CACHE.clear()
    _REGISTRY_CACHE[key] = registry
    return registry


def plugins_enabled(config: dict[str, Any]) -> bool:
    return config_bool(config, "plugins", "enabled", default=True)


def plugin_cache_key(config: dict[str, Any], workspace: Path) -> tuple[Any, ...]:
    plugin_config = plugins_config(config)
    state: list[tuple[str, int, str, int]] = []
    for plugin_dir in discover_plugin_dirs(config, workspace):
        manifest_path = plugin_dir / PLUGIN_MANIFEST
        manifest_mtime = manifest_path.stat().st_mtime_ns
        manifest = read_manifest(manifest_path)
        entrypoint = resolve_plugin_path(plugin_dir, str(manifest.get("entrypoint") or DEFAULT_ENTRYPOINT))
        entrypoint_mtime = entrypoint.stat().st_mtime_ns if entrypoint.exists() else 0
        state.append(
            (
                source_label(manifest_path, workspace),
                manifest_mtime,
                source_label(entrypoint, workspace),
                entrypoint_mtime,
            )
        )
    return (
        str(workspace.resolve()),
        json.dumps(plugin_config, ensure_ascii=False, sort_keys=True, default=str),
        tuple(state),
    )


def plugins_config(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("plugins", {})
    return raw if isinstance(raw, dict) else {}


def load_plugin_registry(config: dict[str, Any], workspace: Path) -> PluginRegistry:
    plugins: list[PluginInfo] = []
    tools: dict[str, PluginTool] = {}

    for plugin_dir in discover_plugin_dirs(config, workspace):
        plugin_tools = load_plugin(plugin_dir, config, workspace)
        if not plugin_tools:
            continue
        plugin = plugin_tools[0].plugin
        plugins.append(plugin)
        for tool in plugin_tools:
            if tool.name in BUILTIN_TOOL_NAMES:
                raise AgentError(f"Plugin {plugin.id!r} tool {tool.name!r} conflicts with a built-in tool.")
            if tool.name in tools:
                raise AgentError(f"Plugin tool {tool.name!r} is declared by more than one plugin.")
            tools[tool.name] = tool

    return PluginRegistry(plugins=tuple(plugins), tools=tools)


def load_plugin(plugin_dir: Path, config: dict[str, Any], workspace: Path) -> list[PluginTool]:
    manifest_path = plugin_dir / PLUGIN_MANIFEST
    manifest = read_manifest(manifest_path)
    if not bool(manifest.get("enabled", True)):
        return []

    plugin_id = normalize_identifier(str(manifest.get("id") or plugin_dir.name), f"{source_label(manifest_path, workspace)} id")
    name = str(manifest.get("name") or plugin_id).strip()
    description = str(manifest.get("description") or "").strip()
    instructions = str(manifest.get("instructions") or "").strip()
    entrypoint = resolve_plugin_path(plugin_dir, str(manifest.get("entrypoint") or DEFAULT_ENTRYPOINT))
    if not entrypoint.is_file():
        raise AgentError(f"Plugin {plugin_id!r} entrypoint not found: {source_label(entrypoint, workspace)}")

    plugin_config = merged_plugin_config(config, manifest, plugin_id)
    plugin = PluginInfo(
        id=plugin_id,
        name=name,
        description=description,
        instructions=instructions,
        plugin_dir=plugin_dir,
        entrypoint=entrypoint,
        config=plugin_config,
    )
    module = load_plugin_module(plugin)

    raw_tools = manifest.get("tools", [])
    if not isinstance(raw_tools, list):
        raise AgentError(f"Plugin {plugin_id!r} tools must be a list.")

    tools: list[PluginTool] = []
    for raw_tool in raw_tools:
        if not isinstance(raw_tool, dict):
            raise AgentError(f"Plugin {plugin_id!r} tool entries must be objects.")
        tool_name = normalize_identifier(str(raw_tool.get("name") or ""), f"{plugin_id} tool name")
        function_name = str(raw_tool.get("function") or tool_name).strip()
        description = str(raw_tool.get("description") or f"{tool_name}(...): plugin tool from {plugin_id}.").strip()
        function = getattr(module, function_name, None)
        if not callable(function):
            raise AgentError(f"Plugin {plugin_id!r} function {function_name!r} is not callable.")
        tools.append(PluginTool(name=tool_name, description=description, plugin=plugin, function=function))
    return tools


def read_manifest(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as file:
            manifest = json.load(file)
    except OSError as exc:
        raise AgentError(f"Could not read plugin manifest {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise AgentError(f"Invalid plugin manifest JSON {path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise AgentError(f"Plugin manifest must be a JSON object: {path}")
    return manifest


def load_plugin_module(plugin: PluginInfo) -> ModuleType:
    source = f"{plugin.entrypoint.resolve()}:{plugin.entrypoint.stat().st_mtime_ns}"
    digest = hashlib.sha256(source.encode("utf-8")).hexdigest()[:16]
    module_name = f"_herald_plugin_{plugin.id}_{digest}"
    if module_name in sys.modules:
        return sys.modules[module_name]

    spec = importlib.util.spec_from_file_location(module_name, plugin.entrypoint)
    if spec is None or spec.loader is None:
        raise AgentError(f"Could not load plugin {plugin.id!r} from {plugin.entrypoint}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        with plugin_sys_path(plugin.plugin_dir):
            spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise AgentError(f"Plugin {plugin.id!r} failed during import: {exc}") from exc
    return module


def execute_plugin_tool(runtime: Any, tool_name: str, args: dict[str, Any]) -> str:
    registry = get_plugin_registry(runtime.config, runtime.workspace)
    tool = registry.tools.get(tool_name)
    if not tool:
        raise AgentError(f"Unknown plugin tool: {tool_name}")

    data_dir = plugin_data_dir(runtime.config, runtime.workspace, tool.plugin.id)
    data_dir.mkdir(parents=True, exist_ok=True)
    context = PluginContext(
        plugin_id=tool.plugin.id,
        workspace=runtime.workspace,
        plugin_dir=tool.plugin.plugin_dir,
        data_dir=data_dir,
        config=tool.plugin.config,
        agent_config=runtime.config,
    )
    try:
        with plugin_sys_path(tool.plugin.plugin_dir):
            result = tool.function(context, **args)
    except TypeError as exc:
        raise AgentError(f"Plugin tool {tool_name} argument error: {exc}") from exc
    except Exception as exc:
        raise AgentError(f"Plugin tool {tool_name} failed: {exc}") from exc
    return serialize_plugin_result(result)


def serialize_plugin_result(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    return json.dumps(result, ensure_ascii=False, indent=2, default=str)


def plugin_tool_schema_text(config: dict[str, Any], workspace: Path) -> str:
    registry = get_plugin_registry(config, workspace)
    if not registry.tools:
        return ""

    lines = ["Plugin tools:"]
    for name in sorted(registry.tools):
        tool = registry.tools[name]
        lines.append(f"- {tool.name}: {tool.description} Plugin: {tool.plugin.id}.")
    return "\n".join(lines)


def plugin_instructions_text(config: dict[str, Any], workspace: Path) -> str:
    registry = get_plugin_registry(config, workspace)
    blocks = []
    for plugin in registry.plugins:
        if plugin.instructions:
            blocks.append(f"[{plugin.id}]\n{plugin.instructions}")
    if not blocks:
        return ""
    return "Plugin instructions:\n" + "\n\n".join(blocks)


def discover_plugin_dirs(config: dict[str, Any], workspace: Path) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for root in plugin_directories(config, workspace):
        candidates = []
        if (root / PLUGIN_MANIFEST).is_file():
            candidates.append(root)
        if root.exists():
            if not root.is_dir():
                raise AgentError(f"Plugin path is not a directory: {root}")
            candidates.extend(child for child in sorted(root.iterdir(), key=lambda item: item.name.lower()) if child.is_dir())
        for candidate in candidates:
            if (candidate / PLUGIN_MANIFEST).is_file() and candidate not in seen:
                found.append(candidate)
                seen.add(candidate)
    return found


def plugin_directories(config: dict[str, Any], workspace: Path) -> list[Path]:
    raw_dirs = plugins_config(config).get("directories", DEFAULT_PLUGIN_DIRS)
    if isinstance(raw_dirs, str):
        raw_items: list[Any] = [raw_dirs]
    elif isinstance(raw_dirs, (list, tuple)):
        raw_items = raw_dirs
    else:
        raise AgentError("plugins.directories must be a string or a list of strings.")

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
            raise AgentError(f"Plugin directory escapes workspace: {raw_text}") from exc
        resolved.append(path)
    return resolved


def plugin_data_dir(config: dict[str, Any], workspace: Path, plugin_id: str) -> Path:
    raw = str(plugins_config(config).get("data_directory") or DEFAULT_PLUGIN_DATA_DIR)
    root = within_workspace(workspace, raw)
    return root / plugin_id


def resolve_plugin_path(plugin_dir: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        raise AgentError(f"Plugin paths must be relative: {raw_path}")
    return path_within(plugin_dir, path, "Plugin path escapes plugin directory")


def path_within(root: Path, path: str | Path, error: str) -> Path:
    raw = Path(path)
    if not raw.is_absolute():
        raw = root / raw
    resolved = raw.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise AgentError(f"{error}: {path}") from exc
    return resolved


def merged_plugin_config(config: dict[str, Any], manifest: dict[str, Any], plugin_id: str) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    manifest_config = manifest.get("config", {})
    if isinstance(manifest_config, dict):
        merged.update(manifest_config)

    runtime_configs = plugins_config(config).get("config", {})
    if isinstance(runtime_configs, dict):
        runtime_config = runtime_configs.get(plugin_id, {})
        if isinstance(runtime_config, dict):
            merged.update(runtime_config)
    return merged


def normalize_identifier(value: str, label: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    normalized = re.sub(r"\s+", "_", normalized)
    if not IDENTIFIER_RE.match(normalized):
        raise AgentError(f"Invalid {label}: {value!r}. Use letters, numbers, and underscores; start with a letter.")
    return normalized


def source_label(path: Path, workspace: Path) -> str:
    try:
        return path.resolve().relative_to(workspace.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


@contextmanager
def plugin_sys_path(plugin_dir: Path) -> Any:
    plugin_path = str(plugin_dir)
    added = plugin_path not in sys.path
    if added:
        sys.path.insert(0, plugin_path)
    try:
        yield
    finally:
        if added:
            try:
                sys.path.remove(plugin_path)
            except ValueError:
                pass
