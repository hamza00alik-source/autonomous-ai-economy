import unittest

from economy.builtin_process import execute_builtin


class BuiltinProcessTests(unittest.TestCase):
    def test_executes_allowlisted_agent_in_child_process(self):
        result = execute_builtin("opportunity-researcher", "  Find   independent evidence ")
        self.assertIn("[opportunity research]", result)
        self.assertIn("Find independent evidence", result)
        self.assertIn("deterministic prototype", result)

    def test_rejects_agent_outside_fixed_allowlist(self):
        with self.assertRaisesRegex(ValueError, "allowlist"):
            execute_builtin("untrusted-agent", "Do work")

    def test_rejects_oversized_objective_before_spawn(self):
        with self.assertRaisesRegex(ValueError, "4096"):
            execute_builtin("verification-auditor", "x" * 4097)


if __name__ == "__main__":
    unittest.main()
