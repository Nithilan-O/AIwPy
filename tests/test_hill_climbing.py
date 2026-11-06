"""Strict improvement, deterministic neighborhoods, bounded classroom traces."""

from dataclasses import replace
import tracemalloc
import unittest
from unittest.mock import patch

from test_astar import tiny_scenario
from tower_defense_optimizer.actions import apply_action, legal_actions
from tower_defense_optimizer.domain import TowerConfiguration, TowerId
from tower_defense_optimizer.evaluation import objective_key
from tower_defense_optimizer.hill_climbing import hill_climbing, format_teaching_trace
from tower_defense_optimizer.search_common import (
    AlgorithmName, SearchLimits, SearchResult, TerminationReason,
)
from tower_defense_optimizer.simulator import SimulationResult, simulate


class HillClimbingTests(unittest.TestCase):
    def test_best_improving_move_and_complete_neighborhoods(self):
        scenario = tiny_scenario()
        with patch('tower_defense_optimizer.simulator.simulate', wraps=simulate) as shared:
            result = hill_climbing(scenario)
        self.assertIsInstance(result, SearchResult)
        self.assertIs(result.algorithm, AlgorithmName.HILL_CLIMBING)
        self.assertIs(result.termination_reason, TerminationReason.LOCAL_OPTIMUM)
        self.assertEqual(result.states_explored, 2)
        self.assertEqual(shared.call_count, 1 + 6 + 3)
        self.assertEqual(result.trace[0].configuration, TowerConfiguration())
        self.assertEqual(result.trace[1].action.tower_type_id, TowerId.SNIPER)
        self.assertEqual(result.trace[1].action.cell_id, (1, 0))
        self.assertGreater(result.trace[1].outcome, result.trace[0].outcome)
        self.assertEqual(result.trace[1].neighbor_outcome, result.trace[1].outcome)
        self.assertEqual([s.neighbors_evaluated for s in result.trace], [6, 3])
        self.assertTrue(all(s.scan_complete for s in result.trace))
        self.assertGreater(result.peak_memory_bytes, 0)
        self.assertGreaterEqual(result.elapsed_seconds, 0)

    def test_equal_and_worse_neighbors_rejected(self):
        scenario = tiny_scenario()
        for neighbor in ((0, 0), (0, 4), (1, 0)):
            # The third case verifies defeated enemies take priority over health.
            initial = SimulationResult(1, 1, 5)
            other = SimulationResult(neighbor[0], 2 - neighbor[0], neighbor[1])
            with self.subTest(neighbor=neighbor):
                with patch('tower_defense_optimizer.simulator.simulate',
                           side_effect=lambda state, _: other if state.placements else initial):
                    result = hill_climbing(scenario)
                self.assertEqual(result.best_configuration, TowerConfiguration())
                self.assertEqual(result.states_explored, 1)
                self.assertIn('equal or worse', result.trace[0].decision)
                self.assertIs(result.termination_reason, TerminationReason.LOCAL_OPTIMUM)
        with patch('tower_defense_optimizer.simulator.simulate',
                   return_value=SimulationResult(1, 1, 5)):
            result = hill_climbing(scenario)
        self.assertEqual(result.best_configuration, TowerConfiguration())

    def test_health_secondary_improvement_and_terminal_local_optimum(self):
        scenario = tiny_scenario(max_towers=1)
        with patch('tower_defense_optimizer.simulator.simulate',
                   side_effect=lambda state, _: SimulationResult(0, 2, len(state.placements))):
            result = hill_climbing(scenario)
        self.assertEqual(len(result.best_configuration.placements), 1)
        self.assertEqual(result.trace[-1].neighbors_evaluated, 0)
        self.assertIn('no legal neighbor', result.trace[-1].decision)
        self.assertIs(result.termination_reason, TerminationReason.LOCAL_OPTIMUM)

    def test_stable_ties_independent_of_action_order(self):
        scenario = tiny_scenario()
        normal = hill_climbing(scenario)
        with patch('tower_defense_optimizer.hill_climbing.legal_actions',
                   side_effect=lambda state, scene: tuple(reversed(legal_actions(state, scene)))):
            reversed_result = hill_climbing(scenario)
        self.assertEqual(normal.best_configuration, reversed_result.best_configuration)
        self.assertEqual(normal.trace, reversed_result.trace)

    def test_expansion_limits_and_accepted_unexpanded_state(self):
        scenario = tiny_scenario()
        for cap in (0, 1, 2):
            result = hill_climbing(scenario, SearchLimits(max_expanded_states=cap))
            self.assertEqual(result.states_explored, cap)
            self.assertEqual(len(result.trace), 0 if cap == 0 else 2)
            self.assertIs(result.termination_reason, TerminationReason.LOCAL_OPTIMUM
                          if cap == 2 else TerminationReason.MAX_EXPANDED_STATES)
            if cap == 0:
                self.assertEqual(result.best_configuration, TowerConfiguration())
            else:
                self.assertEqual(len(result.best_configuration.placements), 1)
            self.assertEqual(result.simulation_result, simulate(result.best_configuration, scenario))
        terminal = hill_climbing(tiny_scenario(budget=0), SearchLimits(max_expanded_states=1))
        self.assertIs(terminal.termination_reason, TerminationReason.LOCAL_OPTIMUM)

    def test_time_limits_zero_and_partial_improving_scan(self):
        scenario = tiny_scenario()
        result = hill_climbing(scenario, SearchLimits(time_limit_seconds=0))
        self.assertEqual(result.trace, ())
        self.assertEqual(result.states_explored, 0)
        self.assertIs(result.termination_reason, TerminationReason.TIME_LIMIT)
        # Expire immediately after evaluating an improving neighbor. No partial
        # best-neighbor scan may cause a move or claim a local optimum.
        now = [0.0]

        def evaluation(state, scene):
            if state.placements:
                now[0] = 2.0
            return SimulationResult(len(state.placements), 2 - len(state.placements), 5)

        with patch('tower_defense_optimizer.search_common.perf_counter', side_effect=lambda: now[0]):
            with patch('tower_defense_optimizer.simulator.simulate', side_effect=evaluation):
                result = hill_climbing(scenario, SearchLimits(time_limit_seconds=1))
        self.assertEqual(result.best_configuration, TowerConfiguration())
        self.assertEqual(result.trace[0].neighbors_evaluated, 1)
        self.assertGreater(result.trace[0].neighbor_outcome, result.trace[0].outcome)
        self.assertFalse(result.trace[0].scan_complete)
        self.assertIs(result.termination_reason, TerminationReason.TIME_LIMIT)
        self.assertFalse(tracemalloc.is_tracing())

    def test_legal_output_repeatability_no_mutation_and_trace_bounds(self):
        scenario = tiny_scenario()
        before = hash(scenario)
        first = hill_climbing(scenario)
        second = hill_climbing(scenario)
        self.assertEqual(hash(scenario), before)
        self.assertEqual(replace(first, elapsed_seconds=0, peak_memory_bytes=0),
                         replace(second, elapsed_seconds=0, peak_memory_bytes=0))
        for step in first.trace:
            scenario.validate_state(step.configuration)
            self.assertEqual(step.outcome, objective_key(simulate(step.configuration, scenario)))
            if step.neighbor_action:
                self.assertIn(step.neighbor_action, legal_actions(step.configuration, scenario))
                self.assertEqual(step.neighbor_configuration,
                                 apply_action(step.configuration, step.neighbor_action, scenario))
        self.assertEqual(first.best_configuration, first.trace[-1].configuration)
        for cap in (0, 1):
            result = hill_climbing(scenario, SearchLimits(max_trace_steps=cap))
            self.assertEqual(result.trace, first.trace[:cap])
            self.assertEqual(result.trace_steps_dropped, len(first.trace) - cap)
            self.assertEqual(result.trace_limit, cap)
            self.assertEqual(result.best_configuration, first.best_configuration)
            self.assertIn('Trace truncated', format_teaching_trace(result, scenario))

    def test_teaching_format(self):
        scenario = tiny_scenario()
        result = hill_climbing(scenario)
        text = format_teaching_trace(result, scenario)
        self.assertTrue(text.startswith('3. Simple Hill Climbing\n'))
        for fragment in ('Initial configuration: empty', 'Stage 0', 'Stage 1',
                         '0 S # B', '1 N + .', 'Best evaluated neighbor',
                         'Move accepted:', 'equal or worse', 'no_improving_neighbor',
                         'no global optimum'):
            self.assertIn(fragment, text)
        self.assertNotIn('Stage 2', text)
        self.assertEqual(text, format_teaching_trace(hill_climbing(scenario), scenario))
        with self.assertRaises(ValueError):
            format_teaching_trace(replace(result, algorithm=AlgorithmName.BFS), scenario)

    def test_exception_cleanup(self):
        with patch('tower_defense_optimizer.simulator.simulate', side_effect=ValueError('bad wave')):
            with self.assertRaisesRegex(ValueError, 'bad wave'):
                hill_climbing(tiny_scenario())
        self.assertFalse(tracemalloc.is_tracing())
        hill_climbing(tiny_scenario(budget=0))
