import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from economy.cgroup_v2 import (
    CgroupUnavailable,
    CgroupV2Limits,
    CPU_PERIOD,
    CPU_QUOTA,
    MEMORY_MAX,
    PIDS_MAX,
)


class CgroupV2Tests(unittest.TestCase):
    def _delegated_root(self, base: Path):
        root = base / "delegated"
        root.mkdir()
        (root / "cgroup.controllers").write_text("cpu memory pids")
        (root / "cgroup.subtree_control").write_text("cpu memory pids")
        mountinfo = base / "mountinfo"
        mountinfo.write_text(f"31 22 0:28 / {base} rw - cgroup2 cgroup rw\n")
        return root, mountinfo

    def test_creates_and_verifies_task_limits(self):
        with tempfile.TemporaryDirectory() as temp:
            root, mountinfo = self._delegated_root(Path(temp))
            limits = CgroupV2Limits.create(root, str(mountinfo))
            try:
                self.assertEqual((limits.path / "memory.max").read_text(), str(MEMORY_MAX))
                self.assertEqual((limits.path / "cpu.max").read_text(), f"{CPU_QUOTA} {CPU_PERIOD}")
                self.assertEqual((limits.path / "pids.max").read_text(), str(PIDS_MAX))
            finally:
                for name in ("memory.max", "cpu.max", "pids.max"):
                    (limits.path / name).unlink(missing_ok=True)
                limits.cleanup()

    def test_rejects_missing_controller(self):
        with tempfile.TemporaryDirectory() as temp:
            root, mountinfo = self._delegated_root(Path(temp))
            (root / "cgroup.subtree_control").write_text("cpu memory")
            with self.assertRaisesRegex(CgroupUnavailable, "enabled cpu, memory and pids"):
                CgroupV2Limits.check_root(root, str(mountinfo))

    def test_rejects_path_outside_cgroup2_mount(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "ordinary"
            root.mkdir()
            (root / "cgroup.controllers").write_text("cpu memory pids")
            (root / "cgroup.subtree_control").write_text("cpu memory pids")
            mountinfo = Path(temp) / "mountinfo"
            mountinfo.write_text("31 22 0:28 / /sys/fs/cgroup rw - cgroup2 cgroup rw\n")
            with self.assertRaisesRegex(CgroupUnavailable, "not on a visible cgroup v2 mount"):
                CgroupV2Limits.check_root(root, str(mountinfo))

    def test_attaches_current_process_to_task_cgroup(self):
        with tempfile.TemporaryDirectory() as temp:
            root, mountinfo = self._delegated_root(Path(temp))
            limits = CgroupV2Limits.create(root, str(mountinfo))
            try:
                procs = limits.path / "cgroup.procs"
                procs.touch()
                with patch("economy.cgroup_v2.os.getpid", return_value=4242):
                    limits.attach_current_process()
                self.assertEqual(procs.read_text(), "4242")
            finally:
                for name in ("memory.max", "cpu.max", "pids.max", "cgroup.procs"):
                    (limits.path / name).unlink(missing_ok=True)
                limits.cleanup()


if __name__ == "__main__":
    unittest.main()
