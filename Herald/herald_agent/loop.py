from __future__ import annotations

from herald_agent.config import response_format_json
from herald_agent.llm import call_llm
from herald_agent.modes import get_mode
from herald_agent.prompts import build_system_prompt
from herald_agent.protocol import extract_json_object
from herald_agent.runtime import Runtime
from herald_agent.tools.registry import execute_tool
from herald_agent.ui import TerminalUI
from herald_agent.utils import truncate


def run_agent(
    task: str,
    runtime: Runtime,
    *,
    interactive: bool = False,
    ui: TerminalUI | None = None,
    show_banner: bool = True,
) -> str:
    limits = runtime.config.get("limits", {})
    max_steps = int(limits.get("max_steps", 12))
    max_observation_chars = int(limits.get("max_observation_chars", 8000))
    model = runtime.config.get("llm", {}).get("model", "unknown")
    mode = get_mode(runtime.config, runtime.workspace)

    if interactive and ui and show_banner:
        ui.banner(task=task, workspace=runtime.workspace, model=model, mode=mode.label, max_steps=max_steps)

    messages = [
        {"role": "system", "content": build_system_prompt(runtime.config, runtime.workspace)},
        {"role": "user", "content": task},
    ]

    for step in range(1, max_steps + 1):
        raw = call_llm(messages, runtime.config)
        messages.append({"role": "assistant", "content": raw})
        try:
            decision = extract_json_object(raw)
        except Exception as exc:
            if should_accept_plain_text_response(runtime.config, raw):
                return raw.strip()
            observation = control_message_error(runtime.config)
            if interactive and ui and should_show_repairs(runtime.config):
                ui.repair(observation)
            messages.append({"role": "user", "content": f"Observation:\n{observation}"})
            continue

        if "final" in decision:
            return str(decision["final"])

        action = decision.get("action")
        if not isinstance(action, dict):
            observation = control_message_error(runtime.config)
            if interactive and ui and should_show_repairs(runtime.config):
                ui.repair(observation)
            messages.append(
                {
                    "role": "user",
                    "content": f"Observation:\n{observation}",
                }
            )
            continue

        if interactive:
            thought = str(decision.get("thought", "")).strip()
            tool_name = action.get("tool", "unknown")
            if ui:
                ui.step(step=step, max_steps=max_steps, tool=str(tool_name), thought=thought)

        try:
            observation = execute_tool(action, runtime)
        except Exception as exc:
            observation = f"TOOL_ERROR: {exc}"
        if interactive and ui:
            ui.observation(observation, is_error=observation.startswith("TOOL_ERROR:"))
        messages.append({"role": "user", "content": "Observation:\n" + truncate(observation, max_observation_chars)})

    return "Stopped: max_steps limit reached before final answer."


def should_accept_plain_text_response(config: dict, raw: str) -> bool:
    if response_format_json(config):
        return False
    stripped = raw.strip()
    if not stripped:
        return False
    return not looks_like_control_attempt(stripped)


def looks_like_json_attempt(text: str) -> bool:
    lowered = text.lower()
    return text.startswith("{") or lowered.startswith("```json") or lowered.startswith("``` json")


def looks_like_control_attempt(text: str) -> bool:
    lowered = text.lower()
    return looks_like_json_attempt(text) or lowered.startswith(("tool", "action", "final"))


def control_message_error(config: dict) -> str:
    if response_format_json(config):
        return "Could not read the control message. Return one valid JSON object with final or action."
    return "Could not read the control message. Use exactly one line: FINAL: answer or TOOL: tool_name {\"arg\":\"value\"}."


def should_show_repairs(config: dict) -> bool:
    return bool(config.get("interface", {}).get("show_repairs", False))
