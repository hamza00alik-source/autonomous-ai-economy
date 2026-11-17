"""Fail-closed cgroup v2 resource limits for an explicitly delegated subtree.

The administrator must delegate a cgroup2 directory with cpu, memory and pids
controllers enabled in cgroup.subtree_control. This module never modifies
system-wide controller configuration.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

MEMORY_MAX = 512 * 1024 * 1024
CPU_PERIOD = 100_000
CPU_QUOTA = 100_000
PIDS_MAX = 16
_REQUIRED = {"cpu", "memory", "pids"}


class CgroupUnavailable(RuntimeError):
    """Raised when a suitable delegated cgroup v2 subtree is unavailable."""


def _unescape_mount_path(value: str) -> str:
    return (value.replace("\\040", " ").replace("\\011", "\t")
            .replace("\\012", "\n").replace("\\134", "\\"))


def _cgroup2_mount_for(root: Path, mountinfo_path: str = "/proc/self/mountinfo") -> Path:
    try:
        lines = Path(mountinfo_path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise CgroupUnavailable("cannot inspect Linux mount information") from exc
    candidates = []
    for line in lines:
        left, separator, right = line.partition(" - ")
        if not separator or not right.startswith("cgroup2 "):
            continue
        fields = left.split()
        if len(fields) < 5:
            continue
        mountpoint = Path(_unescape_mount_path(fields[4])).resolve()
        try:
            root.relative_to(mountpoint)
        except ValueError:
            continue
        candidates.append(mountpoint)
    if not candidates:
        raise CgroupUnavailable("configured root is not on a visible cgroup v2 mount")
    return max(candidates, key=lambda item: len(item.parts))


class CgroupV2Limits:
    """One task's cgroup, attached before the sandbox process is exec'd."""

    def __init__(self, path: Path):
        self.path = path

    @classmethod
    def check_root(cls, root: str | os.PathLike[str],
                   mountinfo_path: str = "/proc/self/mountinfo") -> Path:
        try:
            resolved = Path(root).resolve(strict=True)
        except OSError as exc:
            raise CgroupUnavailable("configured cgroup root does not exist") from exc
        if not resolved.is_dir():
            raise CgroupUnavailable("configured cgroup root is not a directory")
        _cgroup2_mount_for(resolved, mountinfo_path)
        try:
            available = set((resolved / "cgroup.controllers").read_text().split())
            enabled = set((resolved / "cgroup.subtree_control").read_text().split())
        except OSError as exc:
            raise CgroupUnavailable("cannot read delegated cgroup controller files") from exc
        if not _REQUIRED.issubset(available) or not _REQUIRED.issubset(enabled):
            raise CgroupUnavailable("delegated cgroup must expose enabled cpu, memory and pids controllers")
        if not os.access(resolved, os.W_OK | os.X_OK):
            raise CgroupUnavailable("delegated cgroup root is not writable")
        return resolved

    @classmethod
    def create(cls, root: str | os.PathLike[str],
               mountinfo_path: str = "/proc/self/mountinfo") -> "CgroupV2Limits":
        resolved = cls.check_root(root, mountinfo_path)
        child = resolved / f"aae-task-{os.getpid()}-{secrets.token_hex(6)}"
        try:
            child.mkdir(mode=0o700)
            (child / "memory.max").write_text(str(MEMORY_MAX), encoding="ascii")
            (child / "cpu.max").write_text(f"{CPU_QUOTA} {CPU_PERIOD}", encoding="ascii")
            (child / "pids.max").write_text(str(PIDS_MAX), encoding="ascii")
            for filename, expected in (
                ("memory.max", str(MEMORY_MAX)),
                ("cpu.max", f"{CPU_QUOTA} {CPU_PERIOD}"),
                ("pids.max", str(PIDS_MAX)),
            ):
                actual = (child / filename).read_text(encoding="ascii").strip()
                if actual != expected:
                    raise CgroupUnavailable(f"kernel did not retain configured {filename} limit")
        except Exception as exc:
            try:
                child.rmdir()
            except OSError:
                pass
            if isinstance(exc, CgroupUnavailable):
                raise
            raise CgroupUnavailable("failed to create or configure delegated task cgroup") from exc
        return cls(child)

    @property
    def procs_file(self) -> str:
        return str(self.path / "cgroup.procs")

    def attach_current_process(self) -> None:
        """Attach this process; descendants inherit membership across exec/fork."""
        try:
            fd = os.open(self.procs_file, os.O_WRONLY | os.O_CLOEXEC)
            try:
                os.write(fd, str(os.getpid()).encode("ascii"))
            finally:
                os.close(fd)
        except OSError as exc:
            raise CgroupUnavailable("kernel rejected task attachment to delegated cgroup") from exc

    def cleanup(self) -> None:
        try:
            self.path.rmdir()
        except FileNotFoundError:
            return
        except OSError as exc:
            raise CgroupUnavailable("task cgroup is not empty after worker exit") from exc
