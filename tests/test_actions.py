"""Behavioral tests for the common placement contract."""

import unittest
from dataclasses import FrozenInstanceError, replace

from tower_defense_optimizer.actions import (
    PlacementAction,
    apply_action,
    budget_used,
    can_stop,
    is_terminal,
    legal_actions,
)
from tower_defense_optimizer.config import DEFAULT_SCENARIO
from tower_defense_optimizer.domain import Placement, TowerConfiguration, TowerId


class ActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scenario = DEFAULT_SCENARIO
        self.empty = TowerConfiguration()
        self.sites = sorted(self.scenario.buildable_cells)

    def test_empty_state_has_all_cell_type_pairs(self) -> None:
        actions = legal_actions(self.empty, self.scenario)
        expected = tuple(
            PlacementAction(site, tower_id)
            for site in self.sites
            for tower_id in sorted(TowerId, key=lambda item: item.value)
        )
        self.assertEqual(actions, expected)
        self.assertEqual(len(actions), len(set(actions)))
        self.assertEqual(budget_used(self.empty, self.scenario), 0)
        # Each advertised action must produce a scenario-valid configuration.
        for action in actions:
            result = apply_action(self.empty, action, self.scenario)
            self.scenario.validate_state(result)
            self.assertEqual(len(result.placements), 1)

    def test_action_order_independent_of_catalog_and_placement_order(self) -> None:
        scenario = replace(self.scenario, towers=self.scenario.towers[::-1])
        a = Placement(TowerId.ARROW, self.sites[0])
        b = Placement(TowerId.CANNON, self.sites[1])
        state = TowerConfiguration((a, b))
        expected = legal_actions(state, self.scenario)
        self.assertEqual(expected, legal_actions(TowerConfiguration((b, a)), scenario))
        self.assertEqual(expected, legal_actions(state, self.scenario))
        keys = [(item.cell_id, item.tower_type_id.value) for item in expected]
        self.assertEqual(keys, sorted(keys))

    def test_only_buildable_unoccupied_cells_generated(self) -> None:
        occupied = self.sites[0]
        state = TowerConfiguration((Placement(TowerId.ARROW, occupied),))
        actions = legal_actions(state, self.scenario)
        self.assertEqual(
            {action.cell_id for action in actions},
            self.scenario.buildable_cells - {occupied},
        )
        for tower_id in TowerId:
            with self.assertRaises(ValueError):
                apply_action(state, PlacementAction(occupied, tower_id), self.scenario)
        for site in (self.scenario.path[0], (0, 0), (99, 99)):
            with self.subTest(site=site), self.assertRaises(ValueError):
                apply_action(self.empty, PlacementAction(site, TowerId.ARROW),
                             self.scenario)

    def test_budget_boundary_and_accumulated_spending(self) -> None:
        # Leave exactly the Arrow cost after one Sniper and one Cannon.
        state = TowerConfiguration((
            Placement(TowerId.SNIPER, self.sites[0]),
            Placement(TowerId.CANNON, self.sites[1]),
        ))
        self.assertEqual(budget_used(state, self.scenario), 400)
        self.assertEqual(
            {action.tower_type_id for action in legal_actions(state, self.scenario)},
            {TowerId.ARROW},
        )
        action = PlacementAction(self.sites[2], TowerId.ARROW)
        result = apply_action(state, action, self.scenario)
        self.assertEqual(budget_used(result, self.scenario), self.scenario.budget)
        self.assertEqual(legal_actions(result, self.scenario), ())
        self.assertTrue(is_terminal(result, self.scenario))
        for tower_id in (TowerId.CANNON, TowerId.SNIPER):
            with self.assertRaises(ValueError):
                apply_action(state, PlacementAction(self.sites[2], tower_id),
                             self.scenario)
        tighter = replace(self.scenario, budget=self.scenario.budget - 1)
        self.assertEqual(legal_actions(state, tighter), ())
        with self.assertRaises(ValueError):
            apply_action(state, action, tighter)

    def test_maximum_tower_count_with_budget_remaining(self) -> None:
        state = TowerConfiguration(tuple(
            Placement(TowerId.ARROW, site) for site in self.sites[:4]
        ))
        self.assertLess(budget_used(state, self.scenario), self.scenario.budget)
        self.assertEqual(legal_actions(state, self.scenario), ())
        self.assertTrue(is_terminal(state, self.scenario))
        with self.assertRaises(ValueError):
            apply_action(state, PlacementAction(self.sites[4], TowerId.ARROW),
                         self.scenario)

    def test_no_affordable_tower_or_free_site(self) -> None:
        for scenario in (
            replace(self.scenario, budget=0),
            replace(self.scenario, budget=99),
        ):
            self.assertEqual(legal_actions(self.empty, scenario), ())
            self.assertTrue(can_stop(self.empty, scenario))
            self.assertTrue(is_terminal(self.empty, scenario))
        scenario = replace(self.scenario, buildable_cells={self.sites[0]})
        state = apply_action(self.empty,
                             PlacementAction(self.sites[0], TowerId.ARROW), scenario)
        self.assertEqual(legal_actions(state, scenario), ())

    def test_stop_at_every_depth_even_with_legal_extensions(self) -> None:
        state = self.empty
        for depth in range(self.scenario.max_towers + 1):
            self.assertTrue(can_stop(state, self.scenario))
            if depth < self.scenario.max_towers:
                self.assertFalse(is_terminal(state, self.scenario))
                state = apply_action(
                    state, PlacementAction(self.sites[depth], TowerId.ARROW),
                    self.scenario,
                )
        self.assertTrue(is_terminal(state, self.scenario))

    def test_invalid_action_types_and_values(self) -> None:
        for tower_id in ("arrow", "unknown", None, 5):
            with self.subTest(tower_id=tower_id), self.assertRaises(ValueError):
                PlacementAction(self.sites[0], tower_id)
        for cell in ((-1, 0), (True, 0), (1.5, 0), (0,), None):
            with self.subTest(cell=cell), self.assertRaises(ValueError):
                PlacementAction(cell, TowerId.ARROW)
        for action in (None, (self.sites[0], TowerId.ARROW),
                       Placement(TowerId.ARROW, self.sites[0])):
            with self.subTest(action=action), self.assertRaises(ValueError):
                apply_action(self.empty, action, self.scenario)

    def test_invalid_source_states_rejected_by_all_helpers(self) -> None:
        invalid_states = (
            TowerConfiguration((Placement(TowerId.ARROW, (0, 0)),)),
            TowerConfiguration(tuple(
                Placement(TowerId.SNIPER, site) for site in self.sites[:3]
            )),
            TowerConfiguration(tuple(
                Placement(TowerId.ARROW, site) for site in self.sites[:5]
            )),
            None,
        )
        for state in invalid_states:
            for helper in (legal_actions, budget_used, can_stop, is_terminal):
                with self.subTest(state=state, helper=helper.__name__):
                    with self.assertRaises(ValueError):
                        helper(state, self.scenario)
            with self.assertRaises(ValueError):
                apply_action(state, PlacementAction(self.sites[-1], TowerId.ARROW),
                             self.scenario)

    def test_transition_is_canonical_and_preserves_source_hash(self) -> None:
        state = TowerConfiguration((Placement(TowerId.CANNON, self.sites[-1]),))
        original_hash = hash(state)
        cache = {state: "source"}
        action_cell = list(self.sites[0])
        action = PlacementAction(action_cell, TowerId.ARROW)
        action_hash = hash(action)
        action_cell[0] = 99
        result = apply_action(state, action, self.scenario)
        self.assertIsNot(result, state)
        self.assertEqual(result, TowerConfiguration((
            Placement(TowerId.CANNON, self.sites[-1]),
            Placement(TowerId.ARROW, self.sites[0]),
        )))
        self.assertEqual(result.placements[0].cell, self.sites[0])
        self.assertEqual(len(state.placements), 1)
        self.assertEqual(hash(state), original_hash)
        self.assertEqual(cache[state], "source")
        self.assertEqual(hash(action), action_hash)
        with self.assertRaises(FrozenInstanceError):
            action.cell_id = self.sites[1]
        with self.assertRaises(FrozenInstanceError):
            result.placements = ()
        with self.assertRaises(ValueError):
            apply_action(result, action, self.scenario)
        self.assertEqual(hash(state), original_hash)

    def test_cost_is_not_an_ordering_key(self) -> None:
        towers = tuple(replace(tower, cost=1 if tower.id is TowerId.SNIPER else 2)
                       for tower in self.scenario.towers)
        scenario = replace(self.scenario, towers=towers)
        self.assertEqual(legal_actions(self.empty, scenario),
                         legal_actions(self.empty, self.scenario))
