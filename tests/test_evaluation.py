"""One gameplay comparison contract, without spending or runtime tie breakers."""

import unittest
from dataclasses import replace

from tower_defense_optimizer.config import DEFAULT_SCENARIO
from tower_defense_optimizer.domain import TowerConfiguration
from tower_defense_optimizer.evaluation import compare_outcomes, objective_key
from tower_defense_optimizer.simulator import SimulationResult, simulate


class EvaluationTests(unittest.TestCase):
    def test_lexicographic_priority_and_health_tie_break(self) -> None:
        more_defeats = SimulationResult(12, 8, 0)
        fewer_defeats = SimulationResult(11, 9, 10)
        self.assertEqual(objective_key(more_defeats), (12, 0))
        self.assertEqual(compare_outcomes(more_defeats, fewer_defeats), 1)
        self.assertEqual(compare_outcomes(fewer_defeats, more_defeats), -1)
        healthier = replace(more_defeats, base_health_remaining=1)
        self.assertEqual(compare_outcomes(healthier, more_defeats), 1)
        self.assertEqual(compare_outcomes(more_defeats, healthier), -1)

    def test_trace_and_spending_do_not_break_objective_ties(self) -> None:
        scenario = DEFAULT_SCENARIO
        result = simulate(TowerConfiguration(), scenario)
        self.assertEqual(compare_outcomes(result, replace(result, events=())), 0)
        changed_budget = replace(scenario, budget=0)
        self.assertEqual(compare_outcomes(result,
                         simulate(TowerConfiguration(), changed_budget)), 0)
        self.assertEqual(compare_outcomes(result, result), 0)
