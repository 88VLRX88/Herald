from __future__ import annotations

from herald_agent.brain import brain_directory, ensure_brain_directory, is_brain_enabled, set_brain_enabled
from herald_agent.config import config_int
from herald_agent.errors import AgentError
from herald_agent.loop import run_agent
from herald_agent.modes import get_mode, mode_choices_text, set_mode
from herald_agent.runtime import Runtime
from herald_agent.ui import TerminalUI


EXIT_COMMANDS = {"/exit", "/quit", ":q"}


def run_chat(runtime: Runtime, ui: TerminalUI) -> int:
    chat_config = runtime.config.get("chat", {})
    max_turns = int(chat_config.get("max_turns", 100))
    max_context_chars = config_int(runtime.config, "chat", "max_context_chars", default=12000)
    model = runtime.config.get("llm", {}).get("model", "unknown")
    mode = get_mode(runtime.config, runtime.workspace)

    ui.chat_banner(workspace=runtime.workspace, model=model, mode=mode.label, max_turns=max_turns)
    turns: list[tuple[str, str]] = []

    while len(turns) < max_turns:
        try:
            user_text = ui.ask("> ")
        except EOFError:
            ui.status("SESSION CLOSED", "stdin ended", accent="yellow")
            return 0
        except KeyboardInterrupt:
            ui.status("SESSION CLOSED", "interrupted by user", accent="yellow")
            return 130

        user_text = user_text.strip()
        if not user_text:
            continue
        lowered = user_text.lower()
        if lowered in EXIT_COMMANDS:
            ui.status("SESSION CLOSED", "operator disconnected", accent="yellow")
            return 0
        if lowered == "/help":
            ui.chat_help()
            continue
        if lowered == "/brain" or lowered.startswith("/brain "):
            handle_brain_command(user_text, runtime, ui)
            continue
        if lowered == "/mode" or lowered.startswith("/mode "):
            handle_mode_command(user_text, runtime, ui)
            continue
        if lowered == "/clear":
            turns.clear()
            ui.status("MEMORY PURGED", "chat context cleared", accent="cyan")
            continue

        ui.user_message(user_text, turn=len(turns) + 1, memory_chars=context_size(turns))
        task = build_chat_task(user_text, turns, max_context_chars)
        try:
            answer = run_agent(task, runtime, interactive=ui.enabled, ui=ui, show_banner=False)
        except AgentError as exc:
            ui.error(str(exc))
            continue

        ui.agent_message(answer)
        turns.append((user_text, answer))

    ui.status("SESSION LIMIT", f"max chat turns reached: {max_turns}", accent="yellow")
    return 0


def handle_mode_command(user_text: str, runtime: Runtime, ui: TerminalUI) -> None:
    parts = user_text.split(maxsplit=1)
    if len(parts) == 1:
        mode = get_mode(runtime.config, runtime.workspace)
        ui.status("MODE", f"{mode.label}; available: {mode_choices_text(runtime.config, runtime.workspace)}", accent="cyan")
        return
    try:
        mode = set_mode(runtime.config, parts[1], runtime.workspace)
    except AgentError as exc:
        ui.error(str(exc))
        return
    ui.status("MODE", f"selected {mode.label}", accent="cyan")


def handle_brain_command(user_text: str, runtime: Runtime, ui: TerminalUI) -> None:
    parts = user_text.split(maxsplit=1)
    if len(parts) == 1:
        state = "on" if is_brain_enabled(runtime.config) else "off"
        ui.status("BRAIN", f"{state}; use /brain on or /brain off", accent="cyan")
        return

    value = parts[1].strip().lower()
    if value in {"on", "enable", "enabled", "1", "true", "yes", "вкл", "включить"}:
        set_brain_enabled(runtime.config, True)
        ensure_brain_directory(runtime)
        ui.status("BRAIN", f"enabled at {brain_directory(runtime).relative_to(runtime.workspace)}", accent="cyan")
        return
    if value in {"off", "disable", "disabled", "0", "false", "no", "выкл", "выключить"}:
        set_brain_enabled(runtime.config, False)
        ui.status("BRAIN", "disabled", accent="yellow")
        return
    ui.error("Unknown /brain value. Use /brain, /brain on, or /brain off.")


def context_size(turns: list[tuple[str, str]]) -> int:
    return sum(len(user) + len(assistant) for user, assistant in turns)


def build_chat_task(user_text: str, turns: list[tuple[str, str]], max_context_chars: int) -> str:
    if not turns:
        return "Chat mode request:\n" + user_text

    parts = []
    for index, (user, assistant) in enumerate(turns, start=1):
        parts.append(f"Turn {index} user:\n{user}\nTurn {index} assistant:\n{assistant}")

    context = "\n\n".join(parts)
    if len(context) > max_context_chars:
        context = context[-max_context_chars:]

    return (
        "You are inside an interactive CLI chat session. Use the previous dialogue "
        "only as context; answer the current user request.\n\n"
        "Previous dialogue:\n"
        f"{context}\n\n"
        "Current user request:\n"
        f"{user_text}"
    )
