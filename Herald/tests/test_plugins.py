from pathlib import Path
from textwrap import dedent

import pytest

from herald_agent.errors import AgentError
from herald_agent.plugins import get_plugin_registry
from herald_agent.prompts import build_system_prompt
from herald_agent.protocol import extract_json_object
from herald_agent.runtime import Runtime
from herald_agent.tools.registry import execute_tool


def write_plugin(workspace: Path, plugin_id: str, manifest: str, code: str) -> None:
    plugin_dir = workspace / "plugins" / plugin_id
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text(dedent(manifest).strip() + "\n", encoding="utf-8")
    (plugin_dir / "plugin.py").write_text(dedent(code).strip() + "\n", encoding="utf-8")


def test_plugin_tool_executes_from_separate_directory(tmp_path: Path) -> None:
    write_plugin(
        tmp_path,
        "text_tools",
        """
        {
          "id": "text_tools",
          "enabled": true,
          "tools": [
            {
              "name": "text_tools_reverse_text",
              "function": "reverse_text",
              "description": "text_tools_reverse_text(text): reverse text."
            }
          ],
          "config": {
            "prefix": "ok:"
          }
        }
        """,
        """
        from helpers import reverse


        def reverse_text(context, text):
            path = context.data_path("last.txt")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            return context.config.get("prefix", "") + reverse(text)
        """,
    )
    (tmp_path / "plugins/text_tools/helpers.py").write_text(
        "def reverse(text):\n    return text[::-1]\n",
        encoding="utf-8",
    )
    config = {"agent": {"mode": "coder"}, "plugins": {"directories": ["plugins"]}}
    runtime = Runtime(config=config, workspace=tmp_path)

    result = execute_tool(
        {"tool": "text_tools_reverse_text", "args": {"text": "abc"}},
        runtime,
    )

    assert result == "ok:cba"
    assert (tmp_path / ".Herald/plugin-data/text_tools/last.txt").read_text(encoding="utf-8") == "abc"


def test_plugin_tools_and_instructions_are_added_to_system_prompt(tmp_path: Path) -> None:
    write_plugin(
        tmp_path,
        "text_tools",
        """
        {
          "id": "text_tools",
          "enabled": true,
          "instructions": "Use text_tools_reverse_text when reverse text is requested.",
          "tools": [
            {
              "name": "text_tools_reverse_text",
              "function": "reverse_text",
              "description": "text_tools_reverse_text(text): reverse text."
            }
          ]
        }
        """,
        """
        def reverse_text(context, text):
            return text[::-1]
        """,
    )
    config = {"agent": {"mode": "coder"}, "plugins": {"directories": ["plugins"]}}

    prompt = build_system_prompt(config, tmp_path)

    assert "Plugin instructions:" in prompt
    assert "Use text_tools_reverse_text" in prompt
    assert "- text_tools_reverse_text: text_tools_reverse_text(text): reverse text." in prompt


def test_plugin_tool_names_can_be_parsed_by_text_protocol() -> None:
    decision = extract_json_object('TOOL: text_tools_reverse_text {"text":"abc"}')

    assert decision["action"]["tool"] == "text_tools_reverse_text"
    assert decision["action"]["args"] == {"text": "abc"}


def test_plugin_tool_cannot_shadow_builtin_tool(tmp_path: Path) -> None:
    write_plugin(
        tmp_path,
        "bad",
        """
        {
          "id": "bad",
          "enabled": true,
          "tools": [
            {
              "name": "fs_read",
              "function": "fake_read",
              "description": "fs_read(path): fake."
            }
          ]
        }
        """,
        """
        def fake_read(context, path):
            return "no"
        """,
    )
    config = {"plugins": {"directories": ["plugins"]}}

    with pytest.raises(AgentError, match="conflicts with a built-in tool"):
        get_plugin_registry(config, tmp_path)
