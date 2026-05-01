from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from herald_agent.config import config_int
from herald_agent.errors import AgentError
from herald_agent.utils import truncate


DEFAULT_AGENT_JSON_SCHEMA: dict[str, Any] = {
    "name": "herald_agent_control",
    "strict": False,
    "schema": {
        "type": "object",
        "properties": {
            "thought": {"type": "string"},
            "final": {"type": "string"},
            "action": {
                "type": "object",
                "properties": {
                    "tool": {"type": "string"},
                    "args": {"type": "object", "additionalProperties": True},
                },
                "required": ["tool"],
                "additionalProperties": True,
            },
        },
        "additionalProperties": True,
    },
}


def call_llm(messages: list[dict[str, str]], config: dict[str, Any]) -> str:
    llm = config["llm"]
    api_base = llm["api_base"]
    token = llm.get("api_token", "")
    if not token or token.startswith("PUT_"):
        raise AgentError(
            "LLM token is not configured. Set it in agent_config.json or via "
            f"{llm.get('api_token_env', 'the configured env var')}."
        )

    payload: dict[str, Any] = {
        "model": llm["model"],
        "messages": messages,
        "temperature": llm.get("temperature", 0.2),
        "max_tokens": llm.get("max_tokens", 1200),
    }
    response_format = build_response_format(llm)
    if response_format:
        payload["response_format"] = response_format

    timeout = config_int(config, "llm", "timeout_seconds", default=60)
    try:
        data = post_chat_completion(api_base, token, payload, timeout)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if should_retry_without_json_mode(exc.code, body, payload):
            payload["response_format"] = {"type": "text"}
            try:
                data = post_chat_completion(api_base, token, payload, timeout)
            except urllib.error.HTTPError as retry_exc:
                retry_body = retry_exc.read().decode("utf-8", errors="replace")
                raise AgentError(f"LLM HTTP {retry_exc.code}: {truncate(retry_body, 2000)}") from retry_exc
            except urllib.error.URLError as retry_exc:
                raise AgentError(f"LLM request failed: {retry_exc}") from retry_exc
        else:
            raise AgentError(f"LLM HTTP {exc.code}: {truncate(body, 2000)}") from exc
    except urllib.error.URLError as exc:
        raise AgentError(f"LLM request failed: {exc}") from exc

    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise AgentError(f"Unexpected LLM response: {truncate(json.dumps(data), 2000)}") from exc


def build_response_format(llm: dict[str, Any]) -> dict[str, Any] | None:
    response_format_type = configured_api_response_format(llm)
    if response_format_type in {"none", "off", "disabled"}:
        return None
    if response_format_type == "text":
        return {"type": "text"}
    if response_format_type == "json_schema":
        schema = llm.get("response_format_schema") or DEFAULT_AGENT_JSON_SCHEMA
        if not isinstance(schema, dict):
            raise AgentError("llm.response_format_schema must be an object.")
        return {"type": "json_schema", "json_schema": schema}
    if response_format_type == "json_object":
        return {"type": "json_object"}
    raise AgentError(f"Unsupported llm.api_response_format: {response_format_type}")


def configured_api_response_format(llm: dict[str, Any]) -> str:
    explicit = str(llm.get("api_response_format", "")).strip().lower()
    if explicit:
        return explicit

    # Backward compatibility for older configs: only honor response_format_type
    # when the newer response_format_json flag is absent.
    legacy = str(llm.get("response_format_type", "")).strip().lower()
    if legacy and "response_format_json" not in llm:
        return legacy

    return "json_schema" if llm.get("response_format_json", True) else "text"


def post_chat_completion(
    api_base: str,
    token: str,
    payload: dict[str, Any],
    timeout: int,
) -> dict[str, Any]:
    request = urllib.request.Request(
        api_base,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def should_retry_without_json_mode(code: int, body: str, payload: dict[str, Any]) -> bool:
    if code != 400 or payload.get("response_format", {}).get("type") not in {"json_object", "json_schema"}:
        return False
    lowered = body.lower()
    return (
        ("response_format" in lowered and "json_object" in lowered)
        or ("response_format" in lowered and "json_schema" in lowered and "text" in lowered)
    )
