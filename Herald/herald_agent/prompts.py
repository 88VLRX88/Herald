from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

from herald_agent.brain import brain_config, is_brain_enabled
from herald_agent.config import config_bool, response_format_json
from herald_agent.modes import get_mode
from herald_agent.plugins import plugin_instructions_text, plugin_tool_schema_text


def tool_schema_text(config: dict[str, Any], workspace: Path) -> str:
    web = config.get("tools", {}).get("websearch", {})
    delete_state = "enabled" if config_bool(config, "tools", "filesystem", "allow_delete") else "disabled"
    web_provider = web.get("provider", "duckduckgo_html")
    brain_tools = ""
    if is_brain_enabled(config):
        brain_tools = textwrap.dedent(
            """
            - brain_list(max_entries=100): list .Herald knowledge-base notes with links and backlinks.
            - brain_read(path, max_chars=12000): read one .Herald note and its link metadata.
            - brain_write(path, content): create or replace a .Herald .md/.txt note.
            - brain_append(path, content): append text to a .Herald .md/.txt note.
            """
        ).strip()
    return textwrap.dedent(
        f"""
        Available tools:
        - fs_list(path="."): list files under workspace.
        - fs_read(path, max_chars=12000): read a UTF-8 text file.
        - fs_write(path, content): write a UTF-8 text file. Parent dirs are created.
        - fs_append(path, content): append UTF-8 text to a file.
        - fs_mkdir(path): create a directory.
        - fs_delete(path): delete file or empty directory. Currently {delete_state} by config.
        - run_command(command, cwd="."): run a shell command inside workspace.
        - run_python(code, cwd="."): execute a Python snippet inside workspace.
        - web_search(query, limit=5): web search via provider "{web_provider}".
        {brain_tools}
        {plugin_tool_schema_text(config, workspace)}
        """
    ).strip()


def brain_instructions(config: dict[str, Any]) -> str:
    brain = brain_config(config)
    if not is_brain_enabled(config):
        return "Brain memory is disabled. Do not call brain tools."
    directory = brain.get("directory", ".Herald")
    return textwrap.dedent(
        f"""
        Brain memory is enabled in `{directory}`.
        Use it as a small linked knowledge base when the information is likely to matter later:
        durable user preferences, project facts, decisions, research notes, recurring instructions,
        or useful summaries of work already done. Decide on your own when to read, create, or update
        notes. Keep notes concise, use .md or .txt files, and connect related notes with `[[note-name]]`
        or Markdown links. Do not store secrets, credentials, or sensitive personal data.
        """
    ).strip()


def build_system_prompt(config: dict[str, Any], workspace: Path) -> str:
    mode = get_mode(config, workspace)
    if response_format_json(config):
        response_protocol = json_response_protocol()
    else:
        response_protocol = text_response_protocol()

    return textwrap.dedent(
        f"""
        You are a CLI assistant agent running in workspace:
        {workspace}

        Current mode: {mode.label}
        Mode source: {mode.source}
        {mode.instructions}

        {brain_instructions(config)}

        {plugin_instructions_text(config, workspace)}

        Work cycle:
        1. Briefly decide the next smallest useful step.
        2. If you need information or an operation, call exactly one tool.
        3. After observations, continue until the task is done.
        4. Return final only when no more tools are needed.

        Keep reasoning compact. Prefer inspecting files before editing. Do not claim
        a tool result unless it appears in an observation.

        {tool_schema_text(config, workspace)}

        {response_protocol}
        """
    ).strip()


def text_response_protocol() -> str:
    return textwrap.dedent(
        """
        Response protocol:
        - To answer the user, write:
          FINAL: your answer
        - To call one tool, write:
          TOOL: tool_name {"arg":"value"}

        Examples:
        FINAL: Готово.
        TOOL: fs_read {"path":"README.md"}
        TOOL: web_search {"query":"latest Python release", "limit":5}

        Use exactly one FINAL or TOOL message. Do not wrap TOOL calls in prose.
        """
    ).strip()


def json_response_protocol() -> str:
    return textwrap.dedent(
        """
        Respond only with valid JSON in one of these forms:
        {"thought":"why this next step is useful","action":{"tool":"fs_read","args":{"path":"README.md"}}}
        {"thought":"done","final":"final answer for the user"}
        """
    ).strip()
