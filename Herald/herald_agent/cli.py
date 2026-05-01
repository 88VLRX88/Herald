from __future__ import annotations

import argparse
import sys
from pathlib import Path

from herald_agent.brain import ensure_brain_directory, is_brain_enabled, set_brain_enabled
from herald_agent.chat import run_chat
from herald_agent.config import DEFAULT_CONFIG, load_config, resolve_workspace
from herald_agent.errors import AgentError
from herald_agent.loop import run_agent
from herald_agent.modes import mode_choices_text, set_mode
from herald_agent.runtime import Runtime
from herald_agent.tui import run_textual_chat
from herald_agent.ui import TerminalUI


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a small OpenAI-compatible CLI agent.")
    parser.add_argument("task", nargs="*", help="Task for the agent. If omitted, stdin is used.")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help=f"Path to config. Default: {DEFAULT_CONFIG}")
    parser.add_argument("--quiet", action="store_true", help="Hide step progress on stderr.")
    parser.add_argument("--plain", action="store_true", help="Disable terminal UI styling and colors.")
    parser.add_argument("--chat", action="store_true", help="Start an interactive CLI chat session.")
    parser.add_argument(
        "--mode",
        help=f"Agent mode. Defaults: {mode_choices_text()}. Mode files are loaded from agent.mode_dirs.",
    )
    parser.add_argument("--brain", choices=["on", "off"], help="Enable or disable .Herald brain memory for this run.")
    args = parser.parse_args()

    task = " ".join(args.task).strip()
    should_chat = args.chat or (not task and sys.stdin.isatty())
    if not task and not should_chat:
        task = sys.stdin.read().strip()
    if not task and not should_chat:
        print("No task provided.", file=sys.stderr)
        return 2

    try:
        config_path = Path(args.config).resolve()
        config = load_config(config_path)
        if args.brain:
            set_brain_enabled(config, args.brain == "on")
        ui_config = config.get("interface", {})
        ui_enabled = bool(ui_config.get("enabled", True)) and not args.quiet and not args.plain
        ui_backend = str(ui_config.get("backend", "textual")).lower()
        ui = TerminalUI(enabled=ui_enabled, plain=args.plain, config=ui_config)
        runtime = Runtime(config=config, workspace=resolve_workspace(config, config_path))
        if args.mode:
            set_mode(config, args.mode, runtime.workspace)
        if is_brain_enabled(runtime.config):
            ensure_brain_directory(runtime)
        if should_chat and ui_enabled and ui_backend == "textual":
            return run_textual_chat(runtime)
        if should_chat and ui_enabled and ui_backend not in {"terminal", "legacy"}:
            raise AgentError(f"Unknown interface backend: {ui_backend}")
        if should_chat:
            return run_chat(runtime, ui)
        final = run_agent(task, runtime, interactive=ui_enabled, ui=ui)
    except AgentError as exc:
        message = str(exc)
        if "Textual UI is not installed" in message:
            print(f"Error: {message}", file=sys.stderr)
        else:
            TerminalUI(enabled=not args.plain and not args.quiet).error(message)
        return 1

    if args.quiet or args.plain:
        print(final)
    else:
        ui.final(final)
    return 0
