from pathlib import Path

import pytest

from herald_agent.errors import AgentError
from herald_agent.modes import get_mode, mode_choices_text, set_mode


def write_mode(workspace: Path, relpath: str, content: str) -> None:
    path = workspace / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def test_default_modes_are_generated_and_loaded_as_files(tmp_path: Path) -> None:
    config = {"agent": {"mode": "coder"}}

    mode = get_mode(config, tmp_path)

    assert mode.id == "coder"
    assert mode.source == ".Herald/modes/coder.md"
    assert (tmp_path / ".Herald/modes/coder.md").exists()
    assert (tmp_path / ".Herald/modes/research.md").exists()
    assert set_mode(config, "математик", tmp_path).id == "mathematician"
    assert config["agent"]["mode"] == "mathematician"


def test_custom_mode_loads_from_default_brain_modes_dir(tmp_path: Path) -> None:
    write_mode(
        tmp_path,
        ".Herald/modes/reviewer.md",
        """
        ---
        id: code-reviewer
        label: Code Reviewer
        aliases: reviewer, review, ревьюер
        description: Finds bugs, regressions, and missing tests in code changes.
        ---

        Act as a strict code reviewer. Lead with findings ordered by severity.
        """,
    )
    config = {"agent": {"mode": "coder"}}

    mode = set_mode(config, "ревьюер", tmp_path)

    assert mode.id == "code-reviewer"
    assert mode.label == "Code Reviewer"
    assert mode.source == ".Herald/modes/reviewer.md"
    assert config["agent"]["mode"] == "code-reviewer"
    assert "code-reviewer" in mode_choices_text(config, tmp_path)


def test_custom_mode_can_be_retrieved_by_description_and_body(tmp_path: Path) -> None:
    write_mode(
        tmp_path,
        ".Herald/modes/story.md",
        """
        ---
        id: narrative-editor
        label: Narrative Editor
        description: Improves fiction pacing, scenes, character voice, and prose rhythm.
        ---

        Act as a fiction editor. Focus on pacing, scene clarity, character voice,
        continuity, and prose rhythm.
        """,
    )
    config = {"agent": {"mode": "coder"}}

    mode = set_mode(config, "fiction pacing", tmp_path)

    assert mode.id == "narrative-editor"


def test_custom_mode_cannot_duplicate_builtin_alias(tmp_path: Path) -> None:
    write_mode(
        tmp_path,
        ".Herald/modes/dev.md",
        """
        ---
        id: custom-dev
        aliases: dev
        ---

        Act as a custom development assistant.
        """,
    )
    config = {"agent": {"mode": "coder"}}

    with pytest.raises(AgentError, match="already assigned"):
        mode_choices_text(config, tmp_path)
