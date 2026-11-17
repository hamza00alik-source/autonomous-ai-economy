"""Trusted child entrypoint for the built-in deterministic agent runner.

This file intentionally uses only the Python standard library. It is not an
untrusted-code interpreter and must never be extended to eval/exec user code.
"""
import json
import errno
import os
import resource
import socket
import sys

MAX_INPUT = 8192
MAX_OBJECTIVE = 4096
AGENTS = {
    "opportunity-researcher": "opportunity research",
    "verification-auditor": "verification",
}


def _probe_blocked_socket():
    try:
        sock = socket.socket()
    except OSError as exc:
        return exc.errno
    else:
        sock.close()
        return 0


def sandbox_facts():
    """Return kernel-reported identity and inherited limits for parent checks."""
    return {
        "uid": os.getuid(),
        "gid": os.getgid(),
        "cpu_seconds": list(resource.getrlimit(resource.RLIMIT_CPU)),
        "address_space_bytes": list(resource.getrlimit(resource.RLIMIT_AS)),
        "file_size_bytes": list(resource.getrlimit(resource.RLIMIT_FSIZE)),
        "open_files": list(resource.getrlimit(resource.RLIMIT_NOFILE)),
        "seccomp_mode": int(next((line.split()[1] for line in open("/proc/self/status", encoding="ascii") if line.startswith("Seccomp:")), "0")),
        "blocked_socket_errno": _probe_blocked_socket(),
    }


def main():
    raw = sys.stdin.buffer.read(MAX_INPUT + 1)
    if len(raw) > MAX_INPUT:
        raise ValueError("request too large")
    request = json.loads(raw.decode("utf-8"))
    if not isinstance(request, dict) or set(request) != {"agent_id", "objective"}:
        raise ValueError("invalid request shape")
    agent_id = request["agent_id"]
    objective = request["objective"]
    if agent_id not in AGENTS:
        raise ValueError("agent is not in the built-in execution allowlist")
    if not isinstance(objective, str) or not objective.strip() or len(objective) > MAX_OBJECTIVE:
        raise ValueError("objective must be non-empty text of at most 4096 characters")
    clean = " ".join(objective.split())
    role = AGENTS[agent_id]
    result = (f"[{role}] Accepted objective for structured analysis: "
              f"{clean[:500]}. This is a deterministic prototype result, not external research.")
    sys.stdout.write(json.dumps(
        {"result": result, "sandbox": sandbox_facts()},
        separators=(",", ":"),
    ))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        sys.stderr.write(f"{type(exc).__name__}: {exc}"[:1024])
        raise SystemExit(2)
