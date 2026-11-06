"""Tiny complete graph, fixed-depth priority, and conventional heap bookkeeping."""

from dataclasses import replace
from heapq import heappush
from itertools import count
import tracemalloc
import unittest
from unittest.mock import patch

from tower_defense_optimizer.actions import legal_actions
from tower_defense_optimizer.astar import (
    _Frontier, astar, format_teaching_trace, g_cost, heuristic, is_target_depth,
)
from tower_defense_optimizer.bfs import bfs
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
        path=((0, 0), (0, 1), (0, 2)), buildable_cells={(1, 0), (1, 1)},
        towers=tuple(replace(tower, cost=1, range=3, cooldown=1,
                             damage=20 if tower.id is TowerId.SNIPER else 5)
                     for tower in DEFAULT_SCENARIO.towers),
        enemy_count=2, enemy_health=20, budget=2, max_towers=2,
        tick_seconds=1, spawn_interval_seconds=1,
    )
    return replace(scenario, **changes)


class AStarTests(unittest.TestCase):
    def test_scores_goal_predicate_and_shared_result(self) -> None:
        scenario = tiny_scenario()
        with patch("tower_defense_optimizer.simulator.simulate", wraps=simulate) as shared:
            result = astar(scenario)
        self.assertIsInstance(result, SearchResult)
        self.assertIs(result.algorithm, AlgorithmName.ASTAR)
        self.assertIs(result.termination_reason, TerminationReason.EXHAUSTED)
        self.assertEqual(result.states_explored, 16)
        self.assertEqual(shared.call_count, 16)
        self.assertEqual(len(result.trace), 16)
        self.assertEqual(len({step.configuration for step in result.trace}), 16)
        self.assertEqual([step.depth for step in result.trace], [0] + [1] * 6 + [2] * 9)
        for step in result.trace:
            self.assertEqual(g_cost(step.configuration), step.depth)
            self.assertEqual(heuristic(step.configuration, scenario), 2 - step.depth)
            self.assertEqual((step.g, step.h, step.f), (step.depth, 2 - step.depth, 2))
            self.assertEqual(is_target_depth(step.configuration, scenario), step.depth == 2)
        self.assertEqual(sum(is_target_depth(step.configuration, scenario)
                             for step in result.trace), 9)
        self.assertEqual(result.trace[0].configuration, TowerConfiguration())
        self.assertIsNone(result.trace[0].action)
        self.assertGreaterEqual(result.elapsed_seconds, 0)
        self.assertGreater(result.peak_memory_bytes, 0)

    def test_stable_equal_priorities_keep_all_states_and_match_bfs(self) -> None:
        scenario = tiny_scenario()
        result = astar(scenario)
        self.assertEqual(tuple(step.action for step in result.trace[1:7]),
                         legal_actions(TowerConfiguration(), scenario))
        baseline = bfs(scenario)
        self.assertEqual([step.configuration for step in result.trace],
                         [step.configuration for step in baseline.trace])
        self.assertEqual(result.best_configuration, baseline.best_configuration)
        self.assertEqual(result.simulation_result, baseline.simulation_result)

    def test_min_priority_best_g_relaxation_and_stale_entries(self) -> None:
        # Every real route has the same g. Synthetic old expensive routes test
        # conventional relaxation/stale bookkeeping, absent from this graph.
        frontier = _Frontier(tiny_scenario())
        state = TowerConfiguration((Placement(TowerId.ARROW, (1, 0)),))
        empty = TowerConfiguration()
        self.assertTrue(frontier.offer(state, 5, None))  # f=6
        self.assertTrue(frontier.offer(empty, 0, None))  # f=2
        self.assertTrue(frontier.offer(state, 1, None))  # f=2
        self.assertFalse(frontier.offer(state, 1, None))
        self.assertFalse(frontier.offer(state, 6, None))
        self.assertEqual(frontier.pop(), (0, empty, None))
        self.assertEqual(frontier.pop(), (1, state, None))
        self.assertIsNone(frontier.pop())  # old f=6/g=5 version is stale
        self.assertFalse(frontier)

    def test_stale_pop_does_not_simulate_count_or_trace(self) -> None:
        original = _Frontier.offer

        def insert_stale(frontier, state, g, action):
            accepted = original(frontier, state, g, action)
            if g == 0:
                heappush(frontier._heap, (7, 1_000_000, 5, state, action))
            return accepted

        with patch.object(_Frontier, "offer", insert_stale):
            with patch("tower_defense_optimizer.simulator.simulate", wraps=simulate) as shared:
                result = astar(tiny_scenario(), SearchLimits(max_expanded_states=16))
        self.assertEqual(shared.call_count, 16)
        self.assertEqual(result.states_explored, 16)
        self.assertEqual(len(result.trace), 16)
        self.assertIs(result.termination_reason, TerminationReason.EXHAUSTED)

    def test_shallow_best_and_continues_after_goals_and_perfect_defense(self) -> None:
        scenario = tiny_scenario()
        result = astar(scenario)
        self.assertEqual(result.best_configuration,
                         TowerConfiguration((Placement(TowerId.SNIPER, (1, 0)),)))
        self.assertFalse(is_target_depth(result.best_configuration, scenario))
        self.assertEqual(result.simulation_result.enemies_defeated, scenario.enemy_count)
        self.assertEqual(result.states_explored, 16)
        self.assertEqual(result.trace[-1].depth, 2)
        self.assertEqual(objective_key(result.simulation_result),
                         max(step.outcome for step in result.trace))
        scenario.validate_state(result.best_configuration)

    def test_empty_configuration_can_remain_best(self) -> None:
        scenario = tiny_scenario()
        scenario = replace(scenario, towers=tuple(
            replace(tower, damage=1) for tower in scenario.towers
        ))
        result = astar(scenario)
        self.assertEqual(result.best_configuration, TowerConfiguration())
        self.assertEqual(result.states_explored, 16)

    def test_unreachable_depth_due_to_cells_or_budget_is_still_evaluated(self) -> None:
        for scenario, expected_states in (
            (tiny_scenario(max_towers=3), 16),  # only two build sites
            (tiny_scenario(budget=1), 7),
            (tiny_scenario(budget=0), 1),
        ):
            with self.subTest(budget=scenario.budget, target=scenario.max_towers):
                result = astar(scenario)
                self.assertIs(result.termination_reason, TerminationReason.EXHAUSTED)
                self.assertEqual(result.states_explored, expected_states)
                self.assertTrue(all(step.h > 0 for step in result.trace))
                self.assertTrue(all(not is_target_depth(step.configuration, scenario)
                                    for step in result.trace))
                self.assertEqual(objective_key(result.simulation_result),
                                 max(step.outcome for step in result.trace))
                self.assertTrue(any(not legal_actions(step.configuration, scenario)
                                    for step in result.trace))

    def test_state_limit_boundaries_and_valid_best_so_far(self) -> None:
        scenario = tiny_scenario()
        for cap in (0, 1, 4, 15, 16):
            with self.subTest(cap=cap):
                result = astar(scenario, SearchLimits(max_expanded_states=cap))
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

    def test_time_limit_zero_and_during_successors(self) -> None:
        result = astar(tiny_scenario(), SearchLimits(time_limit_seconds=0))
        self.assertIs(result.termination_reason, TerminationReason.TIME_LIMIT)
        self.assertEqual(result.states_explored, 0)
        self.assertEqual(result.trace, ())
        self.assertEqual(result.simulation_result,
                         simulate(TowerConfiguration(), tiny_scenario()))
        with patch("tower_defense_optimizer.search_common.perf_counter",
                   side_effect=count(0, 0.01)):
            result = astar(tiny_scenario(), SearchLimits(time_limit_seconds=0.025))
        self.assertIs(result.termination_reason, TerminationReason.TIME_LIMIT)
        self.assertEqual(result.states_explored, 1)
        self.assertEqual(len(result.trace), 1)
        self.assertFalse(tracemalloc.is_tracing())

    def test_repeatability_no_mutation_and_bounded_trace(self) -> None:
        scenario = tiny_scenario()
        before = hash(scenario)
        first = astar(scenario)
        second = astar(scenario)
        self.assertEqual(hash(scenario), before)
        self.assertEqual(replace(first, elapsed_seconds=0, peak_memory_bytes=0),
                         replace(second, elapsed_seconds=0, peak_memory_bytes=0))
        self.assertEqual(format_teaching_trace(first, scenario),
                         format_teaching_trace(second, scenario))
        for limit in (0, 2):
            result = astar(scenario, SearchLimits(max_trace_steps=limit))
            self.assertEqual(result.trace, first.trace[:limit])
            self.assertEqual(result.trace_steps_dropped, 16 - limit)
            self.assertEqual(result.trace_limit, limit)
            self.assertEqual(result.best_configuration, first.best_configuration)
            self.assertIn("Trace truncated", format_teaching_trace(result, scenario))

    def test_teaching_trace_grid_stages_and_scores(self) -> None:
        scenario = tiny_scenario()
        text = format_teaching_trace(astar(scenario), scenario)
        self.assertTrue(text.startswith("2. A* Algorithm\n"))
        self.assertIn("g=0, h=2, f=2", text)
        self.assertIn("g=1, h=1, f=2", text)
        self.assertIn("g=2, h=0, f=2; target-depth goal: True", text)
        self.assertIn("0 S # B", text)
        self.assertIn("1 N + .", text)
        self.assertIn("h does not estimate defense quality", text)
        self.assertEqual([line for line in text.splitlines() if line.startswith("Stage ")],
                         [f"Stage {i}" for i in range(16)])

    def test_exception_releases_instrumentation(self) -> None:
        with patch("tower_defense_optimizer.simulator.simulate",
                   side_effect=ValueError("invalid wave")):
            with self.assertRaisesRegex(ValueError, "invalid wave"):
                astar(tiny_scenario())
        self.assertFalse(tracemalloc.is_tracing())
        self.assertIs(astar(tiny_scenario(budget=0)).termination_reason,
                      TerminationReason.EXHAUSTED)
