from __future__ import annotations

import json
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from herald_agent.config import config_bool, config_int
from herald_agent.errors import AgentError
from herald_agent.runtime import Runtime, within_workspace
from herald_agent.tools.common import ensure_tool_enabled
from herald_agent.utils import truncate


def command_is_blocked(command: str, denylist: list[str]) -> str | None:
    lowered = command.lower()
    for item in denylist:
        if item.lower() in lowered:
            return item
    return None


def run_command(runtime: Runtime, command: str, cwd: str = ".") -> str:
    ensure_tool_enabled(runtime.config, "execute")
    if not config_bool(runtime.config, "tools", "execute", "allow_shell", default=True):
        raise AgentError("Shell execution is disabled by config.")
    denylist = runtime.config.get("tools", {}).get("execute", {}).get("denylist", [])
    blocked = command_is_blocked(command, denylist)
    if blocked:
        raise AgentError(f"Command blocked by denylist: {blocked}")

    workdir = within_workspace(runtime.workspace, cwd)
    timeout = config_int(runtime.config, "tools", "execute", "timeout_seconds", default=30)
    max_output = config_int(runtime.config, "tools", "execute", "max_output_chars", default=12000)
    try:
        result = subprocess.run(
            command,
            cwd=workdir,
            shell=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        raise AgentError(
            f"Command timed out after {timeout}s.\nstdout:\n{stdout}\nstderr:\n{stderr}"
        ) from exc

    output = {
        "exit_code": result.returncode,
        "stdout": truncate(result.stdout, max_output),
        "stderr": truncate(result.stderr, max_output),
    }
    return json.dumps(output, ensure_ascii=False, indent=2)


def run_python(runtime: Runtime, code: str, cwd: str = ".") -> str:
    ensure_tool_enabled(runtime.config, "execute")
    if not config_bool(runtime.config, "tools", "execute", "allow_python", default=True):
        raise AgentError("Python execution is disabled by config.")

    workdir = within_workspace(runtime.workspace, cwd)
    with tempfile.NamedTemporaryFile("w", suffix=".py", encoding="utf-8", dir=workdir, delete=False) as file:
        file.write(code)
        temp_path = Path(file.name)
    try:
        python = shlex.quote(sys.executable)
        script = shlex.quote(temp_path.name)
        return run_command(runtime, f"{python} {script}", cwd=str(workdir.relative_to(runtime.workspace)))
    finally:
        temp_path.unlink(missing_ok=True)
