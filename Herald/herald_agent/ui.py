from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path
from typing import Any, TextIO


class TerminalUI:
    def __init__(
        self,
        *,
        enabled: bool = True,
        plain: bool = False,
        stream: TextIO | None = None,
        output: TextIO | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.stream = stream or sys.stderr
        self.output = output or sys.stdout
        self.config = config or {}
        self.enabled = enabled
        self.color_enabled = enabled and not plain and self._can_color(self.stream)

    def banner(self, *, task: str, workspace: Path, model: str, mode: str, max_steps: int) -> None:
        if not self.enabled or not self.config.get("show_banner", True):
            return
        self.header(model=model, mode=mode, workspace=workspace)
        self.card("task", task, tone="user", stream=self.stream)

    def chat_banner(self, *, workspace: Path, model: str, mode: str, max_turns: int) -> None:
        if not self.enabled:
            print("Herald chat. /help /brain /mode /clear /exit", file=self.stream)
            return
        self.header(model=model, mode=mode, workspace=workspace)

    def header(self, *, model: str, mode: str, workspace: Path) -> None:
        title = self._color("Herald", "bright")
        meta = self._color(f"{model}  mode={mode}  {workspace}", "muted")
        commands = self._color("/help /brain /mode /clear /exit", "faint")
        print(f"{title}  {meta}", file=self.stream)
        print(f"        {commands}", file=self.stream)
        print(file=self.stream)

    def ask(self, prompt: str) -> str:
        if not sys.stdin.isatty():
            return input()
        if not self.enabled:
            return input(prompt)
        return input(self._color("› ", "prompt"))

    def user_message(self, text: str, *, turn: int, memory_chars: int) -> None:
        if self.enabled:
            self.card("You", text, tone="user", stream=self.stream)

    def chat_help(self) -> None:
        self.card(
            "Commands",
            "/help        show commands\n/brain       show brain state\n/brain on    enable .Herald memory\n/brain off   disable .Herald memory\n/mode        show current mode\n/mode NAME   switch mode\n/clear       clear chat memory\n/exit        close chat",
            tone="system",
            stream=self.stream,
        )

    def agent_message(self, text: str) -> None:
        if not self.enabled:
            print(text, file=self.output)
            return
        self.card("Herald", text, tone="assistant", stream=self.output)

    def step(self, *, step: int, max_steps: int, tool: str, thought: str) -> None:
        if not self.enabled:
            return
        suffix = f"  {thought}" if thought else ""
        self.trace(f"{step}/{max_steps}  {tool}{suffix}", tone="tool")

    def observation(self, text: str, *, is_error: bool = False) -> None:
        if not self.enabled:
            return
        if self.config.get("show_observations", False):
            limit = int(self.config.get("observation_preview_chars", 700))
            preview = text if len(text) <= limit else text[:limit] + f"\n... {len(text) - limit} chars hidden"
            self.card("Tool Error" if is_error else "Tool", preview, tone="error" if is_error else "tool")
            return
        label = "tool error" if is_error else "tool"
        self.trace(f"{label}  {len(text)} chars", tone="error" if is_error else "muted")

    def status(self, label: str, detail: str, *, accent: str = "muted") -> None:
        if self.enabled:
            self.trace(f"{label.lower()}  {detail}", tone=accent)

    def repair(self, message: str) -> None:
        if self.enabled:
            self.card("Repair", message, tone="warning", stream=self.stream)

    def final(self, text: str) -> None:
        if not self.enabled:
            print(text, file=self.output)
            return
        self.card("Herald", text, tone="assistant", stream=self.output)

    def error(self, text: str) -> None:
        if not self.enabled:
            print(f"Error: {text}", file=self.stream)
            return
        self.card("Error", text, tone="error", stream=self.stream)

    def card(self, label: str, text: str, *, tone: str = "system", stream: TextIO | None = None) -> None:
        stream = stream or self.stream
        label_text = self._color(label, tone)
        rail = self._color("│", "rail")
        print(f"{rail} {label_text}", file=stream)
        for line in self._wrap(text).splitlines() or [""]:
            print(f"{rail}   {line}", file=stream)
        print(rail, file=stream)

    def trace(self, text: str, *, tone: str = "muted") -> None:
        print(f"{self._color('•', tone)} {self._color(text, tone)}", file=self.stream)

    def _wrap(self, text: str) -> str:
        lines: list[str] = []
        width = int(self.config.get("wrap_width", 96))
        for raw_line in text.splitlines() or [""]:
            wrapped = textwrap.wrap(raw_line, width=width, replace_whitespace=False) or [""]
            lines.extend(wrapped)
        return "\n".join(lines)

    def _color(self, text: str, style: str) -> str:
        if not self.color_enabled:
            return text
        code = {
            "bright": "38;5;250",
            "faint": "38;5;240",
            "muted": "38;5;245",
            "rail": "38;5;237",
            "prompt": "38;5;252",
            "system": "38;5;247",
            "user": "38;5;252",
            "assistant": "38;5;250",
            "tool": "38;5;242",
            "error": "38;5;203",
            "warning": "38;5;221",
            "cyan": "38;5;247",
            "yellow": "38;5;221",
        }.get(style, "0")
        return f"\033[{code}m{text}\033[0m"

    def _can_color(self, stream: TextIO) -> bool:
        if os.getenv("NO_COLOR") or os.getenv("TERM") == "dumb":
            return False
        return hasattr(stream, "isatty") and stream.isatty()
