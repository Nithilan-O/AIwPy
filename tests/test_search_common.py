"""Shared bookkeeping contracts, without running any search algorithms."""

import tracemalloc
import unittest
from dataclasses import FrozenInstanceError, replace
from unittest.mock import patch

from tower_defense_optimizer.config import DEFAULT_SCENARIO
from tower_defense_optimizer.domain import Placement, TowerConfiguration, TowerId
from tower_defense_optimizer.search_common import (
    AlgorithmName,
    ExpansionTracker,
    RunInstrumentation,
    SearchEvaluator,
    SearchLimitReached,
    SearchLimits,
    SearchResult,
    TerminationReason,
    TraceBuffer,
    TraceStep,
    check_time_limit,
)
from tower_defense_optimizer.simulator import SimulationResult, simulate


class SearchContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.empty = TowerConfiguration()
        self.state = TowerConfiguration((Placement(TowerId.ARROW, (1, 2)),))
        self.outcome = SimulationResult(10, 10, 0)

    def test_result_is_typed_immutable_and_trace_is_copied(self) -> None:
        step = TraceStep(self.empty, None, 0, (10, 0), g=0, h=1, f=1)
        trace = [step]
        result = SearchResult(AlgorithmName.BFS, self.empty, self.outcome,
                              0.25, 1, 1024, TerminationReason.EXHAUSTED, trace)
        trace.clear()
        self.assertEqual(result.trace, (step,))
        self.assertEqual(result.simulation_result, self.outcome)
        self.assertEqual(result.states_explored, 1)
        self.assertIsInstance(hash(result), int)
        with self.assertRaises(FrozenInstanceError):
            result.states_explored = 2
        with self.assertRaises(FrozenInstanceError):
            step.depth = 1
        for changes in (
            {"algorithm": "BFS"}, {"termination_reason": "done"},
            {"elapsed_seconds": float("nan")}, {"states_explored": -1},
            {"peak_memory_bytes": -1}, {"trace_limit": 0},
            {"best_configuration": None}, {"simulation_result": None},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(result, **changes)

    def test_trace_bound_disabled_mode_and_snapshots(self) -> None:
        buffer = TraceBuffer(2)
        first = TraceStep(self.empty, None, 0, (0, 0))
        buffer.append(first)
        snapshot = buffer.steps
        for depth in range(1, 10):
            buffer.append(TraceStep(self.state, None, depth, (10, 0)))
        self.assertEqual(len(buffer.steps), 2)
        self.assertEqual(buffer.dropped_steps, 8)
        self.assertEqual(snapshot, (first,))
        disabled = TraceBuffer(0)
        disabled.append(first)
        self.assertEqual(disabled.steps, ())
        self.assertEqual(disabled.dropped_steps, 1)
        with self.assertRaises(ValueError):
            buffer.append("invalid")
        for changes in ({"depth": -1}, {"outcome": (1,)}, {"outcome": (-1, 0)},
                        {"g": float("inf")}, {"action": "stop"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(first, **changes)

    def test_evaluator_uses_single_simulator_and_keeps_first_on_ties(self) -> None:
        evaluator = SearchEvaluator(DEFAULT_SCENARIO)
        expensive = TowerConfiguration((Placement(TowerId.SNIPER, (1, 2)),))
        with patch("tower_defense_optimizer.simulator.simulate", side_effect=[
            self.outcome, self.outcome, SimulationResult(10, 10, 1),
            SimulationResult(11, 9, 0), SimulationResult(9, 11, 10),
        ]) as shared_simulator:
            evaluator.evaluate(expensive)
            evaluator.evaluate(self.empty)
            self.assertEqual(evaluator.best_configuration, expensive)
            evaluator.evaluate(self.state)
            self.assertEqual(evaluator.best_outcome.base_health_remaining, 1)
            evaluator.evaluate(self.empty)
            self.assertEqual(evaluator.best_configuration, self.empty)
            evaluator.evaluate(expensive)
            self.assertEqual(evaluator.best_configuration, self.empty)
            self.assertEqual(shared_simulator.call_count, 5)
            shared_simulator.assert_called_with(expensive, DEFAULT_SCENARIO)
        step = evaluator.trace_step(self.empty, None, 0, evaluator.best_outcome)
        self.assertEqual(step.outcome, (11, 0))

    def test_real_evaluation_does_not_increment_expansion_count(self) -> None:
        tracker = ExpansionTracker(SearchLimits())
        evaluator = SearchEvaluator(DEFAULT_SCENARIO)
        self.assertEqual(evaluator.evaluate(self.empty), simulate(self.empty, DEFAULT_SCENARIO))
        self.assertEqual(tracker.states_explored, 0)

    def test_unique_expansion_including_initial_goal_and_terminal(self) -> None:
        tracker = ExpansionTracker(SearchLimits(max_expanded_states=2))
        self.assertTrue(tracker.admit(self.empty, 0))
        self.assertFalse(tracker.admit(TowerConfiguration(), 0))
        self.assertTrue(tracker.admit(self.state, 0))
        self.assertEqual(tracker.states_explored, 2)
        # An admitted goal/terminal is counted before its status is inspected.
        # A duplicate at the cap is skipped without consuming another slot.
        self.assertFalse(tracker.admit(self.state, 0))
        other = TowerConfiguration((Placement(TowerId.CANNON, (1, 2)),))
        with self.assertRaises(SearchLimitReached) as caught:
            tracker.admit(other, 0)
        self.assertIs(caught.exception.reason, TerminationReason.MAX_EXPANDED_STATES)
        self.assertEqual(tracker.states_explored, 2)

    def test_canonical_duplicates_only_count_once(self) -> None:
        placements = (Placement(TowerId.ARROW, (1, 2)),
                      Placement(TowerId.CANNON, (3, 4)))
        tracker = ExpansionTracker(SearchLimits())
        self.assertTrue(tracker.admit(TowerConfiguration(placements), 0))
        self.assertFalse(tracker.admit(TowerConfiguration(placements[::-1]), 0))
        self.assertEqual(tracker.states_explored, 1)

    def test_zero_limits_boundary_and_time_precedence(self) -> None:
        limits = SearchLimits(max_expanded_states=0, time_limit_seconds=1)
        tracker = ExpansionTracker(limits)
        with self.assertRaises(SearchLimitReached) as caught:
            tracker.admit(self.empty, 0)
        self.assertIs(caught.exception.reason, TerminationReason.MAX_EXPANDED_STATES)
        with self.assertRaises(SearchLimitReached) as caught:
            tracker.admit(self.empty, 1)
        self.assertIs(caught.exception.reason, TerminationReason.TIME_LIMIT)
        check_time_limit(limits, 0.999)
        with self.assertRaises(SearchLimitReached):
            check_time_limit(SearchLimits(time_limit_seconds=0), 0)
        check_time_limit(SearchLimits(), 1_000_000)
        self.assertEqual(tracker.states_explored, 0)

    def test_limit_validation_and_meaningful_reasons(self) -> None:
        for changes in ({"max_expanded_states": -1}, {"max_expanded_states": True},
                        {"max_trace_steps": -1}, {"time_limit_seconds": -1},
                        {"time_limit_seconds": float("inf")}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                SearchLimits(**changes)
        self.assertEqual(str(SearchLimitReached(TerminationReason.TIME_LIMIT)), "time_limit")
        with self.assertRaises(ValueError):
            SearchLimitReached(TerminationReason.EXHAUSTED)


class InstrumentationTests(unittest.TestCase):
    def test_elapsed_measurement_boundaries(self) -> None:
        with patch("tower_defense_optimizer.search_common.perf_counter",
                   side_effect=[10.0, 10.5, 12.0]):
            with RunInstrumentation() as metrics:
                self.assertEqual(metrics.elapsed_seconds, 0.5)
            self.assertEqual(metrics.elapsed_seconds, 2.0)

    def test_memory_time_and_sequential_runs(self) -> None:
        with RunInstrumentation() as first:
            data = bytearray(100_000)
            self.assertGreaterEqual(first.elapsed_seconds, 0)
        self.assertGreaterEqual(first.peak_memory_bytes, len(data))
        self.assertGreaterEqual(first.elapsed_seconds, 0)
        elapsed = first.elapsed_seconds
        self.assertEqual(first.elapsed_seconds, elapsed)
        self.assertFalse(tracemalloc.is_tracing())
        with RunInstrumentation() as second:
            pass
        self.assertLess(second.peak_memory_bytes, first.peak_memory_bytes)
        self.assertFalse(tracemalloc.is_tracing())
        with self.assertRaises(RuntimeError):
            first.__enter__()

    def test_exception_cleanup_and_overlap_rejection(self) -> None:
        with self.assertRaisesRegex(ValueError, "failure"):
            with RunInstrumentation():
                with self.assertRaises(RuntimeError):
                    with RunInstrumentation():
                        pass
                self.assertTrue(tracemalloc.is_tracing())
                raise ValueError("failure")
        self.assertFalse(tracemalloc.is_tracing())
        with RunInstrumentation():
            pass

    def test_external_tracer_not_reset_or_stopped(self) -> None:
        tracemalloc.start()
        try:
            data = bytearray(100_000)
            peak = tracemalloc.get_traced_memory()[1]
            with self.assertRaises(RuntimeError):
                with RunInstrumentation():
                    pass
            self.assertTrue(tracemalloc.is_tracing())
            self.assertGreaterEqual(tracemalloc.get_traced_memory()[1], peak)
            self.assertEqual(len(data), 100_000)
        finally:
            tracemalloc.stop()
        with RunInstrumentation():
            pass

    def test_failed_initialization_releases_owned_tracer_and_lock(self) -> None:
        with patch("tower_defense_optimizer.search_common.perf_counter",
                   side_effect=RuntimeError("clock failure")):
            with self.assertRaisesRegex(RuntimeError, "clock failure"):
                with RunInstrumentation():
                    pass
        self.assertFalse(tracemalloc.is_tracing())
        with RunInstrumentation():
            pass
