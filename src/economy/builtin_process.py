"""Bounded subprocess execution for trusted built-in deterministic agents.

This adds process separation, a wall-clock timeout, a minimal environment and
POSIX resource limits where available. It is NOT a security sandbox: the child
runs as the same OS user and filesystem permissions, and network isolation is
not enforced. Never use this module to run third-party or user-supplied code.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

MAX_OBJECTIVE = 4096
MAX_RESULT = 2048
TIMEOUT_SECONDS = 5
_ALLOWED = {"opportunity-researcher", "verification-auditor"}
_CHILD = Path(__file__).with_name("_builtin_agent_child.py")


def _limits() -> None:
    """Apply conservative POSIX limits in the child before its interpreter runs."""
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
        resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))
        if hasattr(resource, "RLIMIT_NPROC"):
            resource.setrlimit(resource.RLIMIT_NPROC, (1, 1))
    except (ImportError, OSError, ValueError):
        # Windows and restricted hosts may not expose POSIX rlimits.
        pass


def execute_builtin(agent_id: str, objective: str) -> str:
    if agent_id not in _ALLOWED:
        raise ValueError("agent is not in the built-in execution allowlist")
    if not isinstance(objective, str) or not objective.strip() or len(objective) > MAX_OBJECTIVE:
        raise ValueError("objective must be non-empty text of at most 4096 characters")
    payload = json.dumps(
        {"agent_id": agent_id, "objective": objective},
        separators=(",", ":"),
    ).encode("utf-8")
    if len(payload) > 8192:
        raise ValueError("execution request is too large")

    with tempfile.TemporaryDirectory(prefix="aae-worker-") as workdir:
        try:
            completed = subprocess.run(
                [sys.executable, "-I", "-S", str(_CHILD)],
                input=payload,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=workdir,
                env={},
                timeout=TIMEOUT_SECONDS,
                check=False,
                close_fds=True,
                start_new_session=(os.name == "posix"),
                preexec_fn=_limits if os.name == "posix" else None,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("built-in agent exceeded its execution time limit") from exc
    if completed.returncode != 0:
        message = completed.stderr[:1024].decode("utf-8", errors="replace")
        raise RuntimeError(f"built-in agent process failed: {message}")
    if len(completed.stdout) > 8192:
        raise ValueError("built-in agent response exceeded the output limit")
    try:
        response = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("built-in agent returned an invalid response") from exc
    result = response.get("result") if isinstance(response, dict) else None
    if not isinstance(result, str) or len(result) > MAX_RESULT:
        raise ValueError("built-in agent returned an invalid or oversized result")
    return result
