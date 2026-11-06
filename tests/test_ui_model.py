"""Presentation and optional-startup behavior without requiring a desktop."""

from dataclasses import replace
import subprocess
import sys
import unittest
from unittest.mock import patch

from test_astar import tiny_scenario
from tower_defense_optimizer.application import format_trace, run_searches
from tower_defense_optimizer.domain import Placement, TowerConfiguration, TowerId
from tower_defense_optimizer.search_common import AlgorithmName, SearchLimits
from tower_defense_optimizer.ui_model import (
    ALGORITHM_LABELS, MEASURE_LABELS, grid_cells, parse_limits, result_view,
)


class UIModelTests(unittest.TestCase):
    def test_selection_and_exactly_six_measures(self):
        self.assertEqual(tuple(ALGORITHM_LABELS.values()), ('bfs', 'astar', 'hill-climbing', 'all'))
        self.assertEqual(len(MEASURE_LABELS), 6)
        self.assertFalse(any('coin' in label.lower() or 'cost' in label.lower()
                             for label in MEASURE_LABELS))

    def test_limits_and_actionable_errors(self):
        self.assertEqual(parse_limits('32', '3', '5'), SearchLimits(32, 3, 5))
        self.assertEqual(parse_limits('0', '  ', '0'), SearchLimits(0, None, 0))
        for values, field in ((('-1', '', '5'), 'Explored-state'),
                              (('oops', '', '5'), 'Explored-state'),
                              (('4', 'nan', '5'), 'Time limit'),
                              (('4', 'inf', '5'), 'Time limit'),
                              (('4', '-1', '5'), 'Time limit'),
                              (('4', 'a', '5'), 'Time limit'),
                              (('4', '', '21'), 'Trace stages'),
                              (('4', '', '-1'), 'Trace stages'),
                              (('4', '', '1.2'), 'Trace stages')):
            with self.subTest(values=values), self.assertRaisesRegex(ValueError, field):
                parse_limits(*values)

    def test_grid_coordinates_path_build_sites_and_towers(self):
        scenario = tiny_scenario()
        empty = grid_cells(TowerConfiguration(), scenario)
        self.assertEqual(len(empty), scenario.rows * scenario.columns)
        self.assertEqual([(c.row, c.column) for c in empty],
                         [(r, c) for r in range(2) for c in range(3)])
        self.assertEqual([cell.symbol for cell in empty], ['S', '#', 'B', '+', '+', ''])
        for tower_id, symbol in ((TowerId.ARROW, 'A'), (TowerId.CANNON, 'C'), (TowerId.SNIPER, 'N')):
            state = TowerConfiguration((Placement(tower_id, (1, 0)),))
            before = hash(state), hash(scenario)
            grid = grid_cells(state, scenario)
            self.assertEqual((grid[3].kind, grid[3].symbol), (tower_id.value, symbol))
            self.assertEqual((hash(state), hash(scenario)), before)
        with self.assertRaises(ValueError):
            grid_cells(TowerConfiguration((Placement(TowerId.ARROW, (0, 0)),)), scenario)

    def test_result_metrics_termination_and_teaching_trace_are_original(self):
        scenario = tiny_scenario()
        limits = SearchLimits(20, None, 2)
        results = run_searches('all', scenario, limits)
        for result in results:
            original = replace(result, elapsed_seconds=0.125, peak_memory_bytes=2048)
            with patch('tower_defense_optimizer.simulator.simulate', side_effect=AssertionError):
                view = result_view(original, scenario, limits)
            self.assertEqual(view.measures,
                             ('2', '0', '10', '0.125000', str(result.states_explored), '2.00'))
            self.assertEqual(view.termination, result.termination_reason.value)
            self.assertIn('Sniper at (1, 0)', view.configuration)
            self.assertIn('Stage 0', view.trace)
            self.assertIn('Stage 1', view.trace)
            self.assertNotIn('Stage 2', view.trace)
            self.assertEqual(view.trace, format_trace(result, scenario))
            heading = {AlgorithmName.BFS: '1. BFS', AlgorithmName.ASTAR: '2. A* Algorithm',
                       AlgorithmName.HILL_CLIMBING: '3. Simple Hill Climbing'}[result.algorithm]
            self.assertTrue(view.trace.startswith(heading + '\n'))
            self.assertIn('0 S # B', view.trace)
            self.assertIn('Peak memory is not process RSS', view.explanation)
            if result.algorithm is AlgorithmName.ASTAR:
                self.assertIn('g=0, h=2, f=2', view.trace)
            if result.algorithm is AlgorithmName.HILL_CLIMBING:
                self.assertIn('local optimum', view.explanation)

    def test_zero_limits_and_disabled_trace(self):
        scenario = tiny_scenario()
        limits = SearchLimits(0, None, 0)
        for result in run_searches('all', scenario, limits):
            view = result_view(result, scenario, limits)
            self.assertEqual(view.configuration, 'Empty configuration (no towers)')
            self.assertEqual(view.termination, 'max_expanded_states')
            self.assertNotIn('Stage 0', view.trace)
            self.assertIn('best', view.explanation)

    def test_cli_and_ui_model_import_when_tk_is_missing(self):
        code = '''
import importlib.abc
import sys
class NoTk(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'tkinter' or fullname.startswith('tkinter.'):
            raise ModuleNotFoundError('Tk deliberately unavailable')
sys.meta_path.insert(0, NoTk())
from tower_defense_optimizer.__main__ import main
from tower_defense_optimizer.ui_model import parse_limits
assert main(['--algorithm', 'all', '--max-expanded-states', '0']) == 0
from tower_defense_optimizer import gui
assert gui.main() == 2
'''
        completed = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn('UI unavailable', completed.stderr)
        self.assertIn('1. BFS', completed.stdout)
