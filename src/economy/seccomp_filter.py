"""Small architecture-specific seccomp-BPF denylist for the trusted built-in runner.

This is defense in depth, not a complete syscall allowlist or hostile-code
sandbox. Unknown architectures fail closed rather than running without it.
"""
from __future__ import annotations

import os
import platform
import struct

# Classic BPF opcodes and seccomp return actions.
_BPF_LD_W_ABS = 0x20
_BPF_JMP_JEQ_K = 0x15
_BPF_RET_K = 0x06
_SECCOMP_RET_KILL_PROCESS = 0x80000000
_SECCOMP_RET_ERRNO = 0x00050000
_SECCOMP_RET_ALLOW = 0x7FFF0000

# Audit architecture and syscall numbers for the two CI-supported Linux ABIs.
_POLICIES = {
    "x86_64": (0xC000003E, {
        "socket": 41, "socketpair": 53, "ptrace": 101, "pivot_root": 155,
        "mount": 165, "umount2": 166, "add_key": 248, "request_key": 249,
        "keyctl": 250, "perf_event_open": 298, "bpf": 321, "userfaultfd": 323,
        "io_uring_setup": 425, "io_uring_enter": 426, "io_uring_register": 427,
    }),
    "aarch64": (0xC00000B7, {
        "socket": 198, "socketpair": 199, "ptrace": 117, "pivot_root": 41,
        "mount": 40, "umount2": 39, "add_key": 217, "request_key": 218,
        "keyctl": 219, "perf_event_open": 241, "bpf": 280, "userfaultfd": 282,
        "io_uring_setup": 425, "io_uring_enter": 426, "io_uring_register": 427,
    }),
}


class SeccompUnavailable(RuntimeError):
    """Raised when no reviewed seccomp policy exists for this architecture."""


def build_filter() -> bytes:
    """Build a cBPF program that denies dangerous kernel interfaces."""
    machine = platform.machine().lower()
    if machine not in _POLICIES:
        raise SeccompUnavailable(f"no seccomp policy for architecture: {machine}")
    audit_arch, syscalls = _POLICIES[machine]
    instructions = []

    def stmt(code: int, value: int) -> None:
        instructions.append((code, 0, 0, value))

    def jump(code: int, value: int, jt: int, jf: int) -> None:
        instructions.append((code, jt, jf, value))

    # Kill if the process ABI does not match the reviewed syscall table.
    stmt(_BPF_LD_W_ABS, 4)  # seccomp_data.arch
    jump(_BPF_JMP_JEQ_K, audit_arch, 1, 0)
    stmt(_BPF_RET_K, _SECCOMP_RET_KILL_PROCESS)
    stmt(_BPF_LD_W_ABS, 0)  # seccomp_data.nr
    for number in sorted(set(syscalls.values())):
        jump(_BPF_JMP_JEQ_K, number, 0, 1)
        stmt(_BPF_RET_K, _SECCOMP_RET_ERRNO | 1)  # EPERM
    stmt(_BPF_RET_K, _SECCOMP_RET_ALLOW)
    return b"".join(struct.pack("=HBBI", *item) for item in instructions)


def create_filter_fd() -> int:
    """Return a rewound anonymous file descriptor containing the BPF program."""
    if not hasattr(os, "memfd_create"):
        raise SeccompUnavailable("memfd_create is required for seccomp filter delivery")
    fd = os.memfd_create("aae-seccomp-filter", flags=0)
    try:
        data = build_filter()
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.lseek(fd, 0, os.SEEK_SET)
        return fd
    except Exception:
        os.close(fd)
        raise
