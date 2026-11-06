"""Smoke coverage for the public package and entry point."""

import io
import unittest
from contextlib import redirect_stdout

import tower_defense_optimizer
from tower_defense_optimizer.__main__ import main


class SmokeTest(unittest.TestCase):
    def test_package_import_and_entry_point(self) -> None:
        self.assertEqual(tower_defense_optimizer.__name__, "tower_defense_optimizer")
        output = io.StringIO()
        with redirect_stdout(output):
            status = main()
        self.assertEqual(status, 0)
        self.assertIn("Intelligent Tower Defense Optimizer", output.getvalue())
        self.assertIn("README.md", output.getvalue())
