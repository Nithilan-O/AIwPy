"""Complete tiny-state BFS tests; production scenario values stay unchanged."""

from dataclasses import FrozenInstanceError, replace
from itertools import count, product
import tracemalloc
import unittest
from unittest.mock import patch

from tower_defense_optimizer.actions import PlacementAction, apply_action, legal_actions
from tower_defense_optimizer.bfs import bfs, format_teaching_trace, render_configuration
from tower_defense_optimizer.config import DEFAULT_SCENARIO
from tower_defense_optimizer.domain import Placement, TowerConfiguration, TowerId
from tower_defense_optimizer.evaluation import objective_key
from tower_defense_optimizer.search_common import (
    AlgorithmName, SearchLimits, SearchResult, TerminationReason,
)
from tower_defense_optimizer.simulator import simulate


def tiny_scenario(**changes):
    scenario = replace(
        DEFAULT_SCENARIO, rows=2, columns=3,
        path=((0, 0), (0, 1), (0, 2)),
        buildable_cells={(1, 0), (1, 1)},
        towers=tuple(replace(tower, cost=1, range=3, cooldown=1,
                             damage={TowerId.ARROW: 5, TowerId.CANNON: 10,
                                     TowerId.SNIPER: 20}[tower.id])
                     for tower in DEFAULT_SCENARIO.towers),
        enemy_count=2, enemy_health=20, budget=2, max_towers=2,
        tick_seconds=1, spawn_interval_seconds=1,
    )
    return replace(scenario, **changes)


class BFSTests(unittest.TestCase):
    def test_exhaustive_unique_states_and_terminal_recording(self) -> None:
        scenario = tiny_scenario()
        with patch("tower_defense_optimizer.simulator.simulate", wraps=simulate) as shared:
            result = bfs(scenario)
        self.assertIsInstance(result, SearchResult)
        self.assertIs(result.algorithm, AlgorithmName.BFS)
        self.assertIs(result.termination_reason, TerminationReason.EXHAUSTED)
        # Two sites, each empty or one of three types: 4 * 4 = 16 states.
        self.assertEqual(result.states_explored, 16)
        self.assertEqual(shared.call_count, 16)  # initial fallback is reused
        self.assertEqual(len(result.trace), 16)
        self.assertEqual([step.depth for step in result.trace], [0] + [1] * 6 + [2] * 9)
        expected = {
            TowerConfiguration(tuple(Placement(tower_id, cell)
                for cell, tower_id in zip(sorted(scenario.buildable_cells), types)
                if tower_id is not None))
            for types in product((None, *TowerId), repeat=2)
        }
        expanded = {step.configuration for step in result.trace}
        self.assertEqual(expanded, expected)
        self.assertEqual(len(expanded), result.states_explored)
        terminal_steps = [step for step in result.trace
                          if not legal_actions(step.configuration, scenario)]
        self.assertEqual(len(terminal_steps), 9)
        self.assertTrue(all(step.depth == 2 for step in terminal_steps))
        self.assertGreaterEqual(result.elapsed_seconds, 0)
        self.assertGreater(result.peak_memory_bytes, 0)
        self.assertFalse(tracemalloc.is_tracing())

    def test_best_is_legal_optimal_and_not_first_good_result(self) -> None:
        scenario = tiny_scenario()
        result = bfs(scenario)
        scenario.validate_state(result.best_configuration)
        self.assertEqual(result.simulation_result,
                         simulate(result.best_configuration, scenario))
        self.assertEqual(objective_key(result.simulation_result),
                         max(step.outcome for step in result.trace))
        self.assertEqual(result.best_configuration,
                         TowerConfiguration((Placement(TowerId.SNIPER, (1, 0)),)))
        self.assertEqual(result.simulation_result.enemies_defeated, scenario.enemy_count)
        first_perfect = next(i for i, step in enumerate(result.trace)
                             if step.outcome[0] == scenario.enemy_count)
        self.assertGreater(len(result.trace), first_perfect + 1)

    def test_empty_terminal_scenario(self) -> None:
        scenario = tiny_scenario(budget=0)
        result = bfs(scenario)
        self.assertEqual(result.best_configuration, TowerConfiguration())
        self.assertEqual(result.states_explored, 1)
        self.assertIs(result.termination_reason, TerminationReason.EXHAUSTED)
        self.assertEqual(result.trace[0].configuration, TowerConfiguration())
        self.assertIsNone(result.trace[0].action)
        self.assertEqual(result.simulation_result.enemies_escaped, scenario.enemy_count)

    def test_expansion_caps_and_exact_exhaustion_boundary(self) -> None:
        scenario = tiny_scenario()
        for cap in (0, 1, 4, 15, 16):
            with self.subTest(cap=cap):
                result = bfs(scenario, SearchLimits(max_expanded_states=cap))
                self.assertEqual(result.states_explored, cap)
                self.assertEqual(len(result.trace), cap)
                self.assertIs(result.termination_reason,
                              TerminationReason.EXHAUSTED if cap == 16 else
                              TerminationReason.MAX_EXPANDED_STATES)
                scenario.validate_state(result.best_configuration)
                self.assertEqual(result.simulation_result,
                                 simulate(result.best_configuration, scenario))
                if cap == 0:
                    self.assertEqual(result.best_configuration, TowerConfiguration())

    def test_zero_time_limit_returns_evaluated_empty_fallback(self) -> None:
        scenario = tiny_scenario()
        result = bfs(scenario, SearchLimits(time_limit_seconds=0))
        self.assertIs(result.termination_reason, TerminationReason.TIME_LIMIT)
        self.assertEqual(result.states_explored, 0)
        self.assertEqual(result.trace, ())
        self.assertEqual(result.simulation_result, simulate(TowerConfiguration(), scenario))

    def test_time_limit_during_successors_preserves_best_so_far(self) -> None:
        # Controlled wall-clock observations avoid flaky real-time assertions.
        with patch("tower_defense_optimizer.search_common.perf_counter",
                   side_effect=count(0, 0.01)):
            result = bfs(tiny_scenario(), SearchLimits(time_limit_seconds=0.025))
        self.assertIs(result.termination_reason, TerminationReason.TIME_LIMIT)
        self.assertEqual(result.states_explored, 1)
        self.assertEqual(result.trace[0].configuration, TowerConfiguration())
        self.assertEqual(result.best_configuration, TowerConfiguration())
        self.assertFalse(tracemalloc.is_tracing())

    def test_trace_order_incoming_actions_and_shape(self) -> None:
        scenario = tiny_scenario()
        result = bfs(scenario)
        first_level = result.trace[1:7]
        self.assertEqual(tuple(step.action for step in first_level),
                         legal_actions(TowerConfiguration(), scenario))
        seen = {TowerConfiguration()}
        for step in result.trace:
            self.assertEqual(step.depth, len(step.configuration.placements))
            self.assertIsNone(step.g)
            self.assertIsNone(step.h)
            self.assertIsNone(step.f)
            self.assertEqual(step.outcome,
                             objective_key(simulate(step.configuration, scenario)))
            if step.action is not None:
                parent = TowerConfiguration(tuple(
                    item for item in step.configuration.placements
                    if item.cell != step.action.cell_id
                ))
                self.assertIn(parent, seen)
                self.assertEqual(apply_action(parent, step.action, scenario),
                                 step.configuration)
            seen.add(step.configuration)

    def test_bounded_or_disabled_trace_does_not_change_search(self) -> None:
        scenario = tiny_scenario()
        complete = bfs(scenario)
        for cap in (0, 2):
            with self.subTest(cap=cap):
                result = bfs(scenario, SearchLimits(max_trace_steps=cap))
                self.assertEqual(result.states_explored, 16)
                self.assertEqual(result.trace, complete.trace[:cap])
                self.assertEqual(result.trace_steps_dropped, 16 - cap)
                self.assertEqual(result.trace_limit, cap)
                self.assertEqual(result.best_configuration, complete.best_configuration)
                self.assertEqual(result.simulation_result, complete.simulation_result)
                self.assertIn("Trace truncated", format_teaching_trace(result, scenario))

    def test_stable_repeatability_and_no_mutation(self) -> None:
        scenario = tiny_scenario()
        before = hash(scenario)
        first = bfs(scenario)
        saved = [(step.configuration, hash(step.configuration)) for step in first.trace]
        second = bfs(scenario)
        self.assertEqual(replace(first, elapsed_seconds=0, peak_memory_bytes=0),
                         replace(second, elapsed_seconds=0, peak_memory_bytes=0))
        self.assertEqual(hash(scenario), before)
        self.assertTrue(all(hash(state) == old_hash for state, old_hash in saved))
        self.assertEqual(format_teaching_trace(first, scenario),
                         format_teaching_trace(second, scenario))
        with self.assertRaises(FrozenInstanceError):
            first.trace[0].configuration.placements = ()

    def test_classroom_trace_and_fixed_grid_symbols(self) -> None:
        scenario = tiny_scenario()
        result = bfs(scenario, SearchLimits(max_expanded_states=4))
        text = format_teaching_trace(result, scenario)
        self.assertTrue(text.startswith("1. BFS\n"))
        self.assertEqual([line for line in text.splitlines() if line.startswith("Stage ")],
                         ["Stage 0", "Stage 1", "Stage 2", "Stage 3"])
        self.assertIn("0 S # B", text)
        self.assertIn("A=Arrow, C=Cannon, N=Sniper", text)
        self.assertIn("Path: (0, 0) -> (0, 1) -> (0, 2)", text)
        self.assertIn("1 A + .", text)
        fixed_grid = render_configuration(TowerConfiguration(), DEFAULT_SCENARIO)
        self.assertIn(" 2 S # # # # # # # . .", fixed_grid)
        self.assertIn(" 7 . . . . . . . # # B", fixed_grid)
        self.assertEqual(len(fixed_grid.splitlines()), DEFAULT_SCENARIO.rows + 1)

    def test_instrumentation_cleanup_on_simulation_error(self) -> None:
        with patch("tower_defense_optimizer.simulator.simulate",
                   side_effect=ValueError("invalid wave")):
            with self.assertRaisesRegex(ValueError, "invalid wave"):
                bfs(tiny_scenario())
        self.assertFalse(tracemalloc.is_tracing())
        self.assertIs(bfs(tiny_scenario(budget=0)).termination_reason,
                      TerminationReason.EXHAUSTED)
