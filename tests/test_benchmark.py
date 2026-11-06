"""Benchmark provenance, common inputs, original metrics, and JSON round trips."""

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import asdict, replace
from datetime import datetime
import io
import json
from pathlib import Path
from statistics import median
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from test_astar import tiny_scenario
from tower_defense_optimizer.__main__ import main
from tower_defense_optimizer.application import run_searches
from tower_defense_optimizer.benchmark import (
    RUN_ORDER, export_json, format_benchmark, run_benchmark,
)
from tower_defense_optimizer.domain import Placement, TowerConfiguration, TowerId
from tower_defense_optimizer.search_common import SearchLimits
from tower_defense_optimizer.simulator import simulate


class BenchmarkTests(unittest.TestCase):
    def test_schema_provenance_and_full_shared_configuration(self):
        scenario = tiny_scenario()
        limits = SearchLimits(20, None, 0)
        with patch('tower_defense_optimizer.benchmark.run_searches', wraps=run_searches) as shared:
            report = run_benchmark(scenario, limits, repeats=2)
        self.assertEqual(shared.call_count, 2)
        for call in shared.call_args_list:
            self.assertEqual(call.args[0], 'all')
            self.assertIs(call.args[1], scenario)
            self.assertIs(call.args[2], limits)
        self.assertEqual(report['schema_version'], 1)
        self.assertEqual(set(report), {'schema_version', 'metadata', 'settings',
                                       'settings_sha256', 'runs', 'summary'})
        metadata = report['metadata']
        self.assertTrue(datetime.fromisoformat(metadata['created_at_utc']).tzinfo)
        for field in ('python_version', 'python_implementation', 'platform', 'machine',
                      'implementation_sha256', 'module_sha256', 'measurement_note'):
            self.assertTrue(metadata[field])
        self.assertEqual(metadata['run_order'], list(RUN_ORDER))
        self.assertEqual(metadata['warmup_runs'], 0)
        self.assertEqual(set(report['settings']['scenario']), set(asdict(scenario)))
        self.assertEqual(report['settings']['scenario']['path'], [list(cell) for cell in scenario.path])
        self.assertEqual(report['settings']['limits'], asdict(limits))
        self.assertEqual(len(report['runs']), 6)
        self.assertEqual([r['algorithm'] for r in report['runs']], list(RUN_ORDER) * 2)
        for row in report['runs']:
            self.assertEqual(row['settings_sha256'], report['settings_sha256'])
            self.assertEqual(row['algorithm_version'], metadata['implementation_sha256'])
            self.assertEqual(set(row['metrics']),
                             {'elapsed_seconds', 'states_explored', 'peak_memory_bytes'})
            self.assertEqual(set(row['outcome']),
                             {'enemies_defeated', 'enemies_escaped', 'base_health_remaining'})
        # A different resource budget or wave must have a different identity.
        for changed_scenario, changed_limits in (
            (tiny_scenario(budget=1), limits),
            (tiny_scenario(enemy_count=3), limits),
            (scenario, SearchLimits(1, None, 0)),
        ):
            changed = run_benchmark(changed_scenario, changed_limits)
            self.assertNotEqual(changed['settings_sha256'], report['settings_sha256'])

    def test_metrics_copied_and_medians_correct_without_combining_outcomes(self):
        scenario = tiny_scenario()
        limits = SearchLimits(20, None, 0)
        base = run_searches('all', scenario, limits)
        first = tuple(replace(result, elapsed_seconds=0.2, states_explored=2,
                              peak_memory_bytes=200) for result in base)
        alternative = TowerConfiguration((Placement(TowerId.SNIPER, (1, 1)),))
        second = tuple(replace(result, best_configuration=alternative,
                               simulation_result=simulate(alternative, scenario),
                               elapsed_seconds=0.8, states_explored=4, peak_memory_bytes=400)
                       for result in base)
        with patch('tower_defense_optimizer.benchmark.run_searches', side_effect=[first, second]):
            report = run_benchmark(scenario, limits, repeats=2)
        for row, original in zip(report['runs'], first + second):
            self.assertEqual(row['metrics'], {'elapsed_seconds': original.elapsed_seconds,
                                             'states_explored': original.states_explored,
                                             'peak_memory_bytes': original.peak_memory_bytes})
            self.assertEqual(row['outcome']['enemies_defeated'],
                             original.simulation_result.enemies_defeated)
        for summary in report['summary']:
            self.assertEqual(summary['median_operational_metrics'],
                             {'elapsed_seconds': 0.5, 'states_explored': 3.0,
                              'peak_memory_bytes': 300.0})
            self.assertNotIn('median_outcome', summary)
            groups = summary['configuration_outcomes']
            self.assertEqual(len(groups), 2)
            self.assertEqual(sum(len(group['run_indices']) for group in groups), 2)
            for group in groups:
                row = report['runs'][group['run_indices'][0] - 1]
                self.assertEqual(group['configuration'], row['configuration'])
                self.assertEqual(group['outcome'], row['outcome'])

    def test_repeatable_real_outcomes_legal_configurations_and_accounting(self):
        scenario = tiny_scenario()
        report = run_benchmark(scenario, SearchLimits(20, None, 0), repeats=2)
        for left, right in zip(report['runs'][:3], report['runs'][3:]):
            for field in ('algorithm', 'configuration', 'outcome', 'termination_reason',
                          'limit_stopped', 'result_scope', 'settings_sha256'):
                self.assertEqual(left[field], right[field])
        for row in report['runs']:
            config = TowerConfiguration(tuple(Placement(TowerId(p['tower_id']), tuple(p['cell']))
                                              for p in row['configuration']))
            scenario.validate_state(config)
            outcome = simulate(config, scenario)
            self.assertEqual(row['outcome'], {key: getattr(outcome, key) for key in row['outcome']})
            self.assertEqual(outcome.enemies_defeated + outcome.enemies_escaped, scenario.enemy_count)
            self.assertEqual(outcome.base_health_remaining,
                             max(0, scenario.base_health - outcome.enemies_escaped * scenario.leak_damage))
        for summary in report['summary']:
            rows = [r for r in report['runs'] if r['algorithm'] == summary['algorithm']]
            for name, value in summary['median_operational_metrics'].items():
                self.assertEqual(value, median(row['metrics'][name] for row in rows))
            self.assertEqual(len(summary['configuration_outcomes']), 1)

    def test_resource_limit_flags_and_best_so_far_scope(self):
        for limits, reason in ((SearchLimits(0, None, 0), 'max_expanded_states'),
                               (SearchLimits(20, 0, 0), 'time_limit')):
            report = run_benchmark(tiny_scenario(), limits)
            self.assertTrue(all(row['limit_stopped'] and row['termination_reason'] == reason
                                for row in report['runs']))
            self.assertEqual([row['result_scope'] for row in report['runs']],
                             ['best_evaluated_so_far'] * 2 + ['current_accepted_best_so_far'])
            self.assertTrue(all(row['metrics']['states_explored'] == 0 for row in report['runs']))
            self.assertIn('limit stopped=True', format_benchmark(report))
        report = run_benchmark(tiny_scenario(), SearchLimits(20, None, 0))
        self.assertTrue(all(not row['limit_stopped'] for row in report['runs']))
        self.assertEqual(report['runs'][-1]['result_scope'], 'local_optimum_under_one_placement_moves')
        self.assertEqual(report['runs'][0]['result_scope'], 'best_evaluated_after_exhaustion')

    def test_export_round_trip_and_terminal_summary(self):
        report = run_benchmark(tiny_scenario(), SearchLimits(2, None, 0), repeats=2)
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            export_json(report, path)
            self.assertEqual(json.loads(path.read_text()), report)
        with patch('tower_defense_optimizer.simulator.simulate', side_effect=AssertionError):
            text = format_benchmark(report)
        for fragment in ('Hardware/runtime-sensitive', 'not all process memory or RSS',
                         'Same full scenario', 'Run 1', 'Run 6', 'Median operational',
                         'no gameplay outcomes are averaged', 'limit stopped=', 'scope='):
            self.assertIn(fragment, text)
        self.assertEqual(text.count('  Defeated='), 6)
        self.assertEqual(text.count('  Towers:'), 6)

    def test_invalid_repeats_trace_settings_and_algorithm_set(self):
        for repeats in (0, -1, 1.5, True):
            with self.subTest(repeats=repeats), self.assertRaisesRegex(ValueError, 'at least 1'):
                run_benchmark(repeats=repeats)
        with self.assertRaisesRegex(ValueError, 'max_trace_steps=0'):
            run_benchmark(limits=SearchLimits())
        with patch('tower_defense_optimizer.benchmark.run_searches', return_value=()):
            with self.assertRaisesRegex(ValueError, 'fixed order'):
                run_benchmark()

    def test_cli_benchmark_export_and_actionable_errors(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'report.json'
            output = io.StringIO()
            with redirect_stdout(output):
                status = main(['--benchmark', '--max-expanded-states', '0', '--repeats', '2',
                               '--output', str(path)])
            self.assertEqual(status, 0)
            self.assertEqual(len(json.loads(path.read_text())['runs']), 6)
            self.assertIn('JSON exported to:', output.getvalue())
            for options in (['--benchmark', '--repeats', '0'],
                            ['--benchmark', '--algorithm', 'bfs'], ['--benchmark', '--trace'],
                            ['--repeats', '2'], ['--output', str(path)],
                            ['--benchmark', '--max-expanded-states', '0', '--output', directory]):
                error = io.StringIO()
                with redirect_stderr(error), self.assertRaises(SystemExit) as stopped:
                    main(options)
                self.assertEqual(stopped.exception.code, 2)
                self.assertIn('error:', error.getvalue())
