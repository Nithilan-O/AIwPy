"""Integration of existing searches, simulator, service, and CLI."""

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import unittest
from unittest.mock import patch

from test_astar import tiny_scenario
from tower_defense_optimizer.__main__ import main
from tower_defense_optimizer.application import format_report, run_searches
from tower_defense_optimizer.search_common import (
    AlgorithmName, SearchLimits, SearchResult, TerminationReason,
)
from tower_defense_optimizer.simulator import simulate


class ApplicationTests(unittest.TestCase):
    def test_all_common_shape_legality_simulator_accounting_and_repeatability(self):
        scenario = tiny_scenario()
        before = hash(scenario)
        limits = SearchLimits(max_expanded_states=20, max_trace_steps=3)
        with patch('tower_defense_optimizer.simulator.simulate', wraps=simulate) as shared:
            first = run_searches('all', scenario, limits)
        self.assertEqual(shared.call_count, 16 + 16 + 10)
        self.assertEqual([r.algorithm for r in first], list(AlgorithmName))
        second = run_searches('all', scenario, limits)
        for result, repeated in zip(first, second):
            self.assertIsInstance(result, SearchResult)
            scenario.validate_state(result.best_configuration)
            outcome = result.simulation_result
            self.assertEqual(outcome, simulate(result.best_configuration, scenario))
            self.assertEqual(outcome.enemies_defeated + outcome.enemies_escaped,
                             scenario.enemy_count)
            self.assertEqual(outcome.base_health_remaining,
                             max(0, scenario.base_health - outcome.enemies_escaped * scenario.leak_damage))
            self.assertLessEqual(result.states_explored, limits.max_expanded_states)
            self.assertLessEqual(len(result.trace), limits.max_trace_steps)
            self.assertGreaterEqual(result.elapsed_seconds, 0)
            self.assertGreater(result.peak_memory_bytes, 0)
            self.assertEqual(replace(result, elapsed_seconds=0, peak_memory_bytes=0),
                             replace(repeated, elapsed_seconds=0, peak_memory_bytes=0))
        self.assertEqual(hash(scenario), before)

    def test_one_and_all_dispatch_exact_same_scenario_and_limits(self):
        scenario = tiny_scenario(budget=1)
        limits = SearchLimits(2, None, 1)
        for name in ('bfs', 'astar', 'hill-climbing'):
            with self.subTest(name=name):
                original = run_searches(name, scenario, limits)[0]
                self.assertEqual(len(run_searches(name, scenario, limits)), 1)
                from tower_defense_optimizer import application
                spec = application._ALGORITHMS[name]
                with patch.dict(application._ALGORITHMS,
                                {name: (*spec[:2], lambda s, l: self._same_inputs(
                                    s, l, scenario, limits, original), spec[3])}):
                    run_searches('all', scenario, limits)
        with self.assertRaisesRegex(ValueError, 'choose bfs, astar, hill-climbing, all'):
            run_searches('unknown', scenario, limits)

    def _same_inputs(self, actual_scenario, actual_limits, scenario, limits, result):
        self.assertIs(actual_scenario, scenario)
        self.assertIs(actual_limits, limits)
        return result

    def test_equivalent_zero_resource_limits(self):
        scenario = tiny_scenario()
        for limits, reason in ((SearchLimits(0), TerminationReason.MAX_EXPANDED_STATES),
                               (SearchLimits(time_limit_seconds=0), TerminationReason.TIME_LIMIT)):
            results = run_searches('all', scenario, limits)
            self.assertTrue(all(r.states_explored == 0 and r.termination_reason is reason
                                and not r.best_configuration.placements for r in results))
            self.assertTrue(all(r.simulation_result == simulate(r.best_configuration, scenario)
                                for r in results))

    def test_report_fields_numbering_trace_cap_and_no_resimulation(self):
        scenario = tiny_scenario()
        limits = SearchLimits(20, None, 2)
        results = run_searches('all', scenario, limits)
        # Fix observational metrics to check deterministic formatting in isolation.
        results = tuple(replace(r, elapsed_seconds=0.125, peak_memory_bytes=1234) for r in results)
        with patch('tower_defense_optimizer.simulator.simulate', side_effect=AssertionError):
            text = format_report(results, scenario, limits, trace=True)
        headings = ['1. BFS', '2. A* Algorithm', '3. Simple Hill Climbing']
        self.assertEqual([line for line in text.splitlines() if line in headings], headings)
        self.assertEqual(text.count('Stage 0\n'), 3)
        self.assertEqual(text.count('Stage 1\n'), 3)
        self.assertNotIn('Stage 2\n', text)
        for fragment in ('Sniper [sniper] at (1, 0)', 'defeated=2, escaped=0',
                         'remaining base health=10', 'Runtime: 0.125000 s',
                         'Peak memory: 1234 bytes', 'Explored states:', 'Termination:',
                         'lexicographically', 'Coins spent', 'local optimum',
                         'g=0, h=2, f=2', '0 S # B', 'Trace truncated'):
            self.assertIn(fragment, text)
        self.assertNotIn('Stage 0', format_report(results, scenario, limits))
        empty = run_searches('bfs', tiny_scenario(budget=0), SearchLimits(max_trace_steps=0))
        self.assertIn('empty configuration; no towers',
                      format_report(empty, tiny_scenario(budget=0), SearchLimits(max_trace_steps=0)))

    def test_cli_selection_overrides_and_trace_options(self):
        for selection in ('bfs', 'astar', 'hill-climbing', 'all'):
            with self.subTest(selection=selection):
                output = io.StringIO()
                with patch('tower_defense_optimizer.__main__.DEFAULT_SCENARIO', tiny_scenario()):
                    with redirect_stdout(output):
                        status = main(['--algorithm', selection, '--budget', '1',
                                       '--max-towers', '1', '--max-expanded-states', '2',
                                       '--trace', '--trace-steps', '1'])
                self.assertEqual(status, 0)
                text = output.getvalue()
                self.assertIn('budget=1; max towers=1', text)
                self.assertEqual(text.count('Stage 0\n'), 3 if selection == 'all' else 1)
                self.assertNotIn('Stage 1\n', text)
        output = io.StringIO()
        with redirect_stdout(output):
            main(['--algorithm', 'all', '--time-limit', '0'])
        self.assertNotIn('Stage ', output.getvalue())
        self.assertEqual(output.getvalue().count('Termination: time_limit'), 3)

    def test_cli_actionable_errors_and_help(self):
        for args in (['--algorithm', 'bad'], ['--algorithm', 'bfs', '--budget', '-1'],
                     ['--algorithm', 'all', '--max-towers', '0'],
                     ['--algorithm', 'bfs', '--trace-steps', '-1'],
                     ['--algorithm', 'bfs', '--max-expanded-states', 'oops'],
                     ['--algorithm', 'bfs', '--time-limit', 'nan'],
                     ['--algorithm', 'bfs', '--time-limit', 'inf'],
                     ['--algorithm', 'bfs', '--time-limit', '-1']):
            with self.subTest(args=args):
                error = io.StringIO()
                with redirect_stderr(error), self.assertRaises(SystemExit) as stopped:
                    main(args)
                self.assertEqual(stopped.exception.code, 2)
                self.assertIn('error:', error.getvalue())
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main([]), 0)
        self.assertIn('--algorithm', output.getvalue())
