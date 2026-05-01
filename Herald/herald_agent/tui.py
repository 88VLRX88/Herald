from __future__ import annotations

import importlib.util
import threading
from typing import Any

from herald_agent.brain import ensure_brain_directory, is_brain_enabled, set_brain_enabled
from herald_agent.chat import build_chat_task
from herald_agent.config import config_int
from herald_agent.errors import AgentError
from herald_agent.loop import run_agent
from herald_agent.modes import get_mode, mode_choices_text, set_mode
from herald_agent.runtime import Runtime


def is_textual_available() -> bool:
    return importlib.util.find_spec("textual") is not None


def run_textual_chat(runtime: Runtime) -> int:
    if not is_textual_available():
        raise AgentError(
            "Textual UI is not installed. Install it with: python3 -m pip install -r requirements.txt"
        )

    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.widgets import Footer, Header, Input, Markdown, Static

    class TextualAgentUI:
        enabled = True

        def __init__(self, app: HeraldTextualApp) -> None:
            self.app = app

        def banner(self, **_: Any) -> None:
            return

        def step(self, *, step: int, max_steps: int, tool: str, thought: str) -> None:
            self.app.call_from_thread(self.app.add_tool_step, step, max_steps, tool, thought)

        def observation(self, text: str, *, is_error: bool = False) -> None:
            self.app.call_from_thread(self.app.add_tool_signal, text, is_error)

        def repair(self, message: str) -> None:
            self.app.call_from_thread(self.app.add_notice, "Repair", message, "warning")

        def final(self, text: str) -> None:
            self.app.call_from_thread(self.app.add_assistant_message, text)

        def error(self, text: str) -> None:
            self.app.call_from_thread(self.app.add_notice, "System fault", text, "error")

        def status(self, label: str, detail: str, *, accent: str = "neutral") -> None:
            self.app.call_from_thread(self.app.set_status, label, detail, accent)

    class HeraldTextualApp(App[None]):
        ENABLE_COMMAND_PALETTE = False
        COMMANDS = set()

        CSS = """
        Screen {
            background: #0b0b0c;
            color: #d8d8d8;
        }

        Header {
            background: #111113;
            color: #e4e4e4;
            text-style: bold;
        }

        Footer {
            background: #111113;
            color: #808080;
        }

        #shell {
            height: 100%;
        }

        #main {
            width: 1fr;
            min-width: 60;
            background: #0b0b0c;
        }

        #topbar {
            height: auto;
            padding: 1 3;
            background: #101012;
            border-bottom: solid #242426;
        }

        #brand {
            color: #ededed;
            text-style: bold;
        }

        #subtitle {
            color: #8c8c8c;
        }

        #transcript {
            height: 1fr;
            padding: 1 3;
            background: #0b0b0c;
        }

        #composer {
            height: 5;
            padding: 1 3;
            background: #101012;
            border-top: solid #242426;
        }

        #prompt {
            height: 3;
            background: #171719;
            color: #eeeeee;
            border: round #363638;
        }

        #prompt:focus {
            border: round #6a6a6d;
        }

        #sidebar {
            width: 30;
            padding: 1 2;
            background: #101012;
            border-left: solid #242426;
        }

        .side-title {
            color: #e1e1e1;
            text-style: bold;
            margin: 0 0 1 0;
        }

        .side-line {
            color: #9a9a9c;
            margin: 0 0 1 0;
        }

        .side-value {
            color: #e1e7ef;
        }

        .card {
            width: 100%;
            padding: 1 2;
            margin: 0 0 1 0;
            background: #111113;
            border: round #2b2b2e;
        }

        .user {
            border-left: thick #8f8f94;
            border-top: none;
            border-right: none;
            border-bottom: none;
            background: #141416;
        }

        .assistant {
            border-left: thick #d0d0d2;
            border-top: none;
            border-right: none;
            border-bottom: none;
            background: #111113;
        }

        .tool {
            border-left: thick #707073;
            border-top: none;
            border-right: none;
            border-bottom: none;
            background: #0f0f11;
        }

        .signal {
            border-left: thick #555558;
            border-top: none;
            border-right: none;
            border-bottom: none;
            background: #0f0f11;
        }

        .error {
            border-left: thick #c76f6f;
            border-top: none;
            border-right: none;
            border-bottom: none;
            background: #181213;
        }

        .warning {
            border-left: thick #9a8f6a;
            border-top: none;
            border-right: none;
            border-bottom: none;
            background: #171512;
        }

        .muted {
            color: #7d8792;
        }

        .accent {
            color: #dddddd;
        }
        """

        BINDINGS = [
            ("ctrl+c", "quit", "Quit"),
            ("ctrl+l", "clear_chat", "Clear"),
        ]

        def __init__(self, runtime: Runtime) -> None:
            super().__init__()
            self.runtime = runtime
            self.turns: list[tuple[str, str]] = []
            self.busy = False
            self.max_turns = int(runtime.config.get("chat", {}).get("max_turns", 100))
            self.max_context_chars = config_int(runtime.config, "chat", "max_context_chars", default=12000)
            self.model = runtime.config.get("llm", {}).get("model", "unknown")
            self.mode = get_mode(runtime.config, runtime.workspace)
            self.brain_enabled = is_brain_enabled(runtime.config)

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            with Horizontal(id="shell"):
                with Vertical(id="main"):
                    with Vertical(id="topbar"):
                        yield Static("Herald", id="brand")
                        yield Static(f"local agent - {self.mode.label}", id="subtitle")
                    yield VerticalScroll(id="transcript")
                    with Vertical(id="composer"):
                        yield Input(placeholder="Ask the agent. Use /help, /brain, /mode, /clear, /exit.", id="prompt")
                with Vertical(id="sidebar"):
                    yield Static("SESSION", classes="side-title")
                    yield Static(f"model    {self.model}", classes="side-line")
                    yield Static(f"mode     {self.mode.label}", id="mode", classes="side-line")
                    yield Static(f"brain    {self.brain_state()}", id="brain", classes="side-line")
                    yield Static(f"workdir  {self.runtime.workspace}", classes="side-line")
                    yield Static(f"turns    0/{self.max_turns}", id="turns", classes="side-line")
                    yield Static("status   online", id="status", classes="side-line")
                    yield Static("tool     idle", id="tool-status", classes="side-line")
                    yield Static("tools", classes="side-title")
                    yield Static("fs / exec / web / brain", classes="side-line")
                    yield Static("commands", classes="side-title")
                    yield Static("/help  /brain  /mode  /clear  /exit", classes="side-line")
            yield Footer()

        def on_mount(self) -> None:
            self.title = "Herald"
            self.sub_title = "Agent"
            self.add_notice(
                "Ready",
                "Ask a question or request a file/code action.",
                "signal",
            )
            self.query_one("#prompt", Input).focus()

        def on_input_submitted(self, event: Input.Submitted) -> None:
            value = event.value.strip()
            prompt = self.query_one("#prompt", Input)
            prompt.value = ""
            if not value:
                return

            lowered = value.lower()
            if lowered in {"/exit", "/quit", ":q"}:
                self.exit()
                return
            if lowered == "/help":
                self.add_notice(
                    "Commands",
                    "/help shows this panel\n/brain shows brain state\n/brain on enables .Herald memory\n/brain off disables .Herald memory\n/mode shows the current mode\n/mode NAME switches mode\n/clear clears chat memory\n/exit closes the console",
                    "signal",
                )
                return
            if lowered == "/brain" or lowered.startswith("/brain "):
                self.handle_brain_command(value)
                return
            if lowered == "/mode" or lowered.startswith("/mode "):
                self.handle_mode_command(value)
                return
            if lowered == "/clear":
                self.turns.clear()
                self.query_one("#transcript", VerticalScroll).remove_children()
                self.update_turns()
                self.add_notice("Memory cleared", "Current chat context was removed.", "signal")
                return

            if self.busy:
                self.add_notice("Agent busy", "Wait for the current response before sending another message.", "warning")
                return
            if len(self.turns) >= self.max_turns:
                self.add_notice("Session limit", f"Maximum turns reached: {self.max_turns}", "warning")
                return

            self.add_user_message(value)
            self.busy = True
            prompt.disabled = True
            prompt.placeholder = "Agent is thinking..."
            self.set_status("status", "running", "accent")

            thread = threading.Thread(target=self._run_turn, args=(value,), daemon=True)
            thread.start()

        def action_clear_chat(self) -> None:
            self.turns.clear()
            self.query_one("#transcript", VerticalScroll).remove_children()
            self.update_turns()
            self.add_notice("Memory cleared", "Current chat context was removed.", "signal")

        def _run_turn(self, user_text: str) -> None:
            task = build_chat_task(user_text, self.turns, self.max_context_chars)
            ui = TextualAgentUI(self)
            try:
                answer = run_agent(task, self.runtime, interactive=True, ui=ui, show_banner=False)
            except AgentError as exc:
                self.call_from_thread(self.finish_error, str(exc))
                return
            self.call_from_thread(self.finish_answer, user_text, answer)

        def finish_answer(self, user_text: str, answer: str) -> None:
            self.add_assistant_message(answer)
            self.turns.append((user_text, answer))
            self.update_turns()
            self.finish_turn()

        def finish_error(self, message: str) -> None:
            self.add_notice("System fault", message, "error")
            self.finish_turn()

        def finish_turn(self) -> None:
            self.busy = False
            prompt = self.query_one("#prompt", Input)
            prompt.disabled = False
            prompt.placeholder = "Ask the agent. Use /help, /brain, /mode, /clear, /exit."
            self.set_status("status", "online", "signal")
            self.set_tool_status("idle", "signal")
            prompt.focus()

        def handle_brain_command(self, value: str) -> None:
            parts = value.split(maxsplit=1)
            if len(parts) == 1:
                self.add_notice("Brain", f"Current: {self.brain_state()}\nUse /brain on or /brain off.", "signal")
                return
            raw = parts[1].strip().lower()
            if raw in {"on", "enable", "enabled", "1", "true", "yes", "вкл", "включить"}:
                set_brain_enabled(self.runtime.config, True)
                ensure_brain_directory(self.runtime)
                self.brain_enabled = True
                self.update_brain()
                self.add_notice("Brain", "Enabled .Herald memory.", "signal")
                return
            if raw in {"off", "disable", "disabled", "0", "false", "no", "выкл", "выключить"}:
                set_brain_enabled(self.runtime.config, False)
                self.brain_enabled = False
                self.update_brain()
                self.add_notice("Brain", "Disabled .Herald memory.", "signal")
                return
            self.add_notice("Brain", "Unknown value. Use /brain, /brain on, or /brain off.", "warning")

        def handle_mode_command(self, value: str) -> None:
            parts = value.split(maxsplit=1)
            if len(parts) == 1:
                mode = get_mode(self.runtime.config, self.runtime.workspace)
                self.add_notice(
                    "Mode",
                    f"Current: {mode.label}\nAvailable: {mode_choices_text(self.runtime.config, self.runtime.workspace)}",
                    "signal",
                )
                return
            try:
                self.mode = set_mode(self.runtime.config, parts[1], self.runtime.workspace)
            except AgentError as exc:
                self.add_notice("Mode", str(exc), "warning")
                return
            self.update_mode()
            self.add_notice("Mode changed", f"Selected: {self.mode.label}", "signal")

        def add_user_message(self, text: str) -> None:
            self.add_card(
                "You",
                text,
                "user",
                markdown=False,
            )

        def add_assistant_message(self, text: str) -> None:
            self.add_card("Herald", text, "assistant", markdown=True)

        def add_tool_step(self, step: int, max_steps: int, tool: str, thought: str) -> None:
            body = f"{step}/{max_steps}  {tool}"
            if thought:
                body += f"\n{thought}"
            self.add_card("Tool", body, "tool", markdown=False)
            self.set_tool_status(tool, "accent")

        def add_tool_signal(self, text: str, is_error: bool) -> None:
            kind = "error" if is_error else "signal"
            label = "Tool Error" if is_error else "Tool Result"
            preview = text if len(text) <= 500 else text[:500] + f"\n... {len(text) - 500} chars hidden"
            if is_error or self.runtime.config.get("interface", {}).get("show_observations", False):
                self.add_card(label, preview, kind, markdown=False)
            else:
                self.set_tool_status(f"{len(text)} chars", "signal")

        def add_notice(self, title: str, body: str, kind: str = "signal") -> None:
            self.add_card(title, body, kind, markdown=False)

        def add_card(self, title: str, body: str, kind: str, *, markdown: bool) -> None:
            transcript = self.query_one("#transcript", VerticalScroll)
            if markdown:
                card = Markdown(f"**{title}**\n\n{body}", classes=f"card {kind}")
            else:
                card = Static(f"{title}\n\n{body}", classes=f"card {kind}")
            transcript.mount(card)
            self.call_after_refresh(transcript.scroll_end, animate=False)

        def set_status(self, label: str, value: str, accent: str = "signal") -> None:
            status = self.query_one("#status", Static)
            status.update(f"{label:<8} {value}")
            status.set_classes(f"side-line {accent}")

        def update_turns(self) -> None:
            self.query_one("#turns", Static).update(f"turns    {len(self.turns)}/{self.max_turns}")

        def update_mode(self) -> None:
            self.query_one("#mode", Static).update(f"mode     {self.mode.label}")
            self.query_one("#subtitle", Static).update(f"local agent - {self.mode.label}")

        def brain_state(self) -> str:
            return "on" if self.brain_enabled else "off"

        def update_brain(self) -> None:
            self.query_one("#brain", Static).update(f"brain    {self.brain_state()}")

        def set_tool_status(self, value: str, accent: str = "signal") -> None:
            status = self.query_one("#tool-status", Static)
            status.update(f"tool     {value}")
            status.set_classes(f"side-line {accent}")

    app = HeraldTextualApp(runtime)
    app.run()
    return 0
