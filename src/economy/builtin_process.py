"""Fail-closed Linux bubblewrap runner for trusted built-in deterministic agents.

Untrusted third-party code is NOT supported. The child is restricted by a
separate mount/PID/network namespace and a read-only runtime filesystem. Hosts
without bubblewrap fail closed rather than silently running without isolation.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

try:
    import resource
except ImportError:
    resource = None
from pathlib import Path

MAX_OBJECTIVE = 4096
MAX_RESULT = 2048
TIMEOUT_SECONDS = 5
_ALLOWED = {"opportunity-researcher", "verification-auditor"}
_CHILD = Path(__file__).with_name("_builtin_agent_child.py")
_RUNTIME_PATHS = ("/usr", "/bin", "/lib", "/lib64")


class SandboxUnavailable(RuntimeError):
    """Raised when the host cannot provide the required OS isolation."""


def ensure_sandbox_available() -> str:
    """Return Bubblewrap or fail before claiming work on unsupported hosts."""
    if os.name != "posix" or resource is None:
        raise SandboxUnavailable("Linux/POSIX resource isolation is required")
    bwrap = shutil.which("bwrap")
    if not bwrap:
        raise SandboxUnavailable(
            "bubblewrap is required; refusing to execute without OS isolation"
        )
    return bwrap


def _sandbox_command(bwrap: str, payload: bytes) -> list[str]:
    del payload  # Request is supplied on stdin, never through command arguments.
    command = [
        bwrap,
        "--die-with-parent",
        "--new-session",
        "--unshare-all",
        "--cap-drop", "ALL",
        "--clearenv",
    ]
    mounted = []
    for host_path in _RUNTIME_PATHS:
        if Path(host_path).exists():
            command.extend(["--ro-bind", host_path, host_path])
            mounted.append(Path(host_path).resolve())
    prefix = Path(sys.prefix).resolve()
    if not any(prefix == root or root in prefix.parents for root in mounted):
        for parent in reversed(prefix.parents):
            if str(parent) != "/":
                command.extend(["--dir", str(parent)])
        command.extend(["--ro-bind", str(prefix), str(prefix)])
    command.extend([
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
        "--dir", "/runner",
        "--ro-bind", str(_CHILD), "/runner/child.py",
        "--dir", "/work",
        "--chdir", "/work",
        "--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin",
        "--setenv", "HOME", "/nonexistent",
        "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
        "--uid", "65534",
        "--gid", "65534",
        sys.executable,
        "-I",
        "-S",
        "/runner/child.py",
    ])
    return command


def _apply_process_limits() -> None:
    """Apply inherited hard limits to Bubblewrap and every sandbox descendant."""
    if resource is None:
        raise SandboxUnavailable("POSIX resource limits are unavailable")
    resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
    if hasattr(resource, "RLIMIT_NPROC"):
        resource.setrlimit(resource.RLIMIT_NPROC, (32, 32))

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

    bwrap = ensure_sandbox_available()
    command = _sandbox_command(bwrap, payload)
    try:
        completed = subprocess.run(
            command,
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=TIMEOUT_SECONDS,
            check=False,
            close_fds=True,
            env={},
            preexec_fn=_apply_process_limits if resource is not None else None,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("sandboxed built-in agent exceeded its execution time limit") from exc
    if completed.returncode != 0:
        message = completed.stderr[:1024].decode("utf-8", errors="replace")
        raise RuntimeError(f"sandboxed built-in agent failed: {message}")
    if len(completed.stdout) > 8192:
        raise ValueError("sandboxed built-in agent response exceeded the output limit")
    try:
        response = json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("sandboxed built-in agent returned an invalid response") from exc
    result = response.get("result") if isinstance(response, dict) else None
    if not isinstance(result, str) or len(result) > MAX_RESULT:
        raise ValueError("sandboxed built-in agent returned an invalid or oversized result")
    return result
