from __future__ import annotations

import ast
import json
import re
from typing import Any

from herald_agent.errors import AgentError
from herald_agent.utils import truncate


TOOL_NAMES = {
    "fs_list",
    "fs_read",
    "fs_write",
    "fs_append",
    "fs_mkdir",
    "fs_delete",
    "run_command",
    "run_python",
    "web_search",
    "brain_list",
    "brain_read",
    "brain_write",
    "brain_append",
}

POSITIONAL_ARGS = {
    "fs_list": ["path"],
    "fs_read": ["path", "max_chars"],
    "fs_write": ["path", "content"],
    "fs_append": ["path", "content"],
    "fs_mkdir": ["path"],
    "fs_delete": ["path"],
    "run_command": ["command", "cwd"],
    "run_python": ["code", "cwd"],
    "web_search": ["query", "limit"],
    "brain_list": ["max_entries"],
    "brain_read": ["path", "max_chars"],
    "brain_write": ["path", "content"],
    "brain_append": ["path", "content"],
}


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    value = parse_text_protocol(stripped) if looks_like_text_protocol(stripped) else None
    if value is None:
        value = parse_structured_response(stripped)
    if value is None:
        value = parse_text_protocol(stripped)
    if value is None:
        raise AgentError(f"Model did not return a supported control message: {truncate(text, 1000)}")
    if not isinstance(value, dict):
        raise AgentError("Model control response must be an object.")
    return value


def looks_like_text_protocol(text: str) -> bool:
    stripped = strip_fence(text).lstrip().lower()
    return stripped.startswith(("final:", "tool:", "action:"))


def parse_structured_response(text: str) -> dict[str, Any] | None:
    candidates = []
    candidates.append(strip_fence(text))
    candidates.extend(extract_brace_candidates(text))

    for candidate in candidates:
        value = parse_object_literal(candidate)
        if isinstance(value, dict):
            return value
    return None


def parse_object_literal(text: str) -> Any:
    cleaned = strip_fence(text).strip()
    cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    try:
        return ast.literal_eval(cleaned)
    except (SyntaxError, ValueError):
        return None


def strip_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    stripped = re.sub(r"^```(?:json|text)?\s*", "", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def extract_brace_candidates(text: str) -> list[str]:
    candidates = []
    starts = [index for index, char in enumerate(text) if char == "{"]
    for start in starts:
        depth = 0
        in_string = False
        quote = ""
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == quote:
                    in_string = False
                continue
            if char in {'"', "'"}:
                in_string = True
                quote = char
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start : index + 1])
                    break
    return candidates


def parse_text_protocol(text: str) -> dict[str, Any] | None:
    stripped = strip_fence(text)
    final_match = re.match(r"(?is)^\s*FINAL\s*:\s*(.+)$", stripped)
    if final_match:
        return {"final": final_match.group(1).strip()}

    tool_call = parse_tool_line(stripped)
    if tool_call:
        return tool_call

    function_call = parse_function_call(stripped)
    if function_call:
        return function_call

    return None


def parse_tool_line(text: str) -> dict[str, Any] | None:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        match = re.match(r"(?i)^(?:TOOL|ACTION)\s*:\s*([a-z_][a-z0-9_]*)\s*(.*)$", line)
        if not match:
            continue
        tool = match.group(1)
        remainder = match.group(2).strip()
        if not remainder and index + 1 < len(lines):
            args_match = re.match(r"(?i)^ARGS?\s*:\s*(.+)$", lines[index + 1])
            if args_match:
                remainder = args_match.group(1).strip()
        return {"thought": "tool call", "action": {"tool": tool, "args": parse_args(tool, remainder)}}
    return None


def parse_function_call(text: str) -> dict[str, Any] | None:
    match = re.match(r"(?s)^\s*([a-z_][a-z0-9_]*)\s*\((.*)\)\s*$", text.strip(), flags=re.IGNORECASE)
    if not match:
        return None
    tool = match.group(1)
    args = parse_call_args(tool, match.group(2))
    return {"thought": "tool call", "action": {"tool": tool, "args": args}}


def parse_args(tool: str, text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        return {}
    if stripped.startswith(("args=", "ARGS=")):
        stripped = stripped.split("=", 1)[1].strip()

    value = parse_object_literal(stripped)
    if isinstance(value, dict):
        if "args" in value and isinstance(value["args"], dict):
            return value["args"]
        return value

    key_value_args = parse_key_value_args(stripped)
    if key_value_args:
        return key_value_args

    default_keys = POSITIONAL_ARGS.get(tool, [])
    if default_keys:
        return {default_keys[0]: stripped.strip("\"'")}
    return {}


def parse_key_value_args(text: str) -> dict[str, Any]:
    args: dict[str, Any] = {}
    for match in re.finditer(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s,]+)", text):
        raw_value = match.group(2)
        value = parse_scalar(raw_value)
        args[match.group(1)] = value
    return args


def parse_call_args(tool: str, args_text: str) -> dict[str, Any]:
    keys = POSITIONAL_ARGS.get(tool, [])
    try:
        expression = ast.parse(f"_tool({args_text})", mode="eval")
    except SyntaxError:
        return parse_args(tool, args_text)
    call = expression.body
    if not isinstance(call, ast.Call):
        return {}

    args: dict[str, Any] = {}
    for index, node in enumerate(call.args):
        if index >= len(keys):
            break
        args[keys[index]] = literal_node_value(node)
    for keyword in call.keywords:
        if keyword.arg:
            args[keyword.arg] = literal_node_value(keyword.value)
    return args


def literal_node_value(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        if isinstance(node, ast.Name):
            return node.id
        return ""


def parse_scalar(text: str) -> Any:
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        lowered = text.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if lowered == "null":
            return None
        try:
            return int(text)
        except ValueError:
            return text.strip("\"'")
