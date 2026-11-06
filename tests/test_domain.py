"""Focused validation and canonical-state contracts for the fixed scenario."""

import unittest
from dataclasses import FrozenInstanceError, replace

from tower_defense_optimizer.config import DEFAULT_SCENARIO
from tower_defense_optimizer.domain import (
    Placement,
    TowerConfiguration,
    TowerId,
)


class ScenarioTests(unittest.TestCase):
    def test_default_scenario_path_and_towers(self) -> None:
        scenario = DEFAULT_SCENARIO
        self.assertEqual((scenario.rows, scenario.columns), (10, 10))
        self.assertEqual(scenario.enemy_count, 20)
        self.assertEqual((scenario.budget, scenario.max_towers), (500, 4))
        self.assertEqual({tower.id for tower in scenario.towers}, set(TowerId))
        self.assertEqual(len(scenario.path), len(set(scenario.path)))
        self.assertNotEqual(scenario.path[0], scenario.path[-1])
        self.assertTrue(all(scenario.contains(cell) for cell in scenario.path))
        self.assertTrue(all(
            abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1
            for a, b in zip(scenario.path, scenario.path[1:])
        ))
        self.assertFalse(scenario.buildable_cells.intersection(scenario.path))

    def test_invalid_paths(self) -> None:
        for path in (
            (), ((2, 0),), ((2, 0), (2, 1), (2, 0)),
            ((2, 0), (2, 1), (2, 2), (2, 1), (3, 1)),
            ((2, 0), (3, 1)), ((2, 0), (2, 2)),
            ((0, 9), (0, 10)), ((-1, 0), (0, 0)),
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                replace(DEFAULT_SCENARIO, path=path)

    def test_invalid_buildable_cells(self) -> None:
        for cells in (set(), {(2, 0)}, {(10, 0)}, {(0, -1)}):
            with self.subTest(cells=cells), self.assertRaises(ValueError):
                replace(DEFAULT_SCENARIO, buildable_cells=cells)

    def test_invalid_scenario_numbers(self) -> None:
        invalid = {
            "rows": [0, True], "columns": [-1, 2.5], "enemy_count": [0],
            "enemy_health": [-1], "enemy_speed": [0, float("nan")],
            "leak_damage": [0], "budget": [-1, True], "max_towers": [0],
            "base_health": [0], "tick_seconds": [0, 2],
            "spawn_interval_seconds": [0, 0.01],
            "max_wave_seconds": [float("inf"), 0.01],
        }
        for name, values in invalid.items():
            for value in values:
                with self.subTest(name=name, value=value):
                    with self.assertRaises(ValueError):
                        replace(DEFAULT_SCENARIO, **{name: value})

    def test_invalid_tower_catalogs(self) -> None:
        arrow, cannon, sniper = DEFAULT_SCENARIO.towers
        for towers in (
            (), (arrow, cannon), (arrow, cannon, cannon),
            (arrow, cannon, sniper, arrow),
            (arrow, cannon, replace(sniper, name=arrow.name)),
            (arrow, cannon, "sniper"),
        ):
            with self.subTest(towers=towers), self.assertRaises(ValueError):
                replace(DEFAULT_SCENARIO, towers=towers)

    def test_scenario_copies_mutable_inputs(self) -> None:
        path = [list(cell) for cell in DEFAULT_SCENARIO.path]
        sites = set(DEFAULT_SCENARIO.buildable_cells)
        towers = list(DEFAULT_SCENARIO.towers)
        scenario = replace(DEFAULT_SCENARIO, path=path,
                           buildable_cells=sites, towers=towers)
        path[0][0] = 9
        sites.clear()
        towers.clear()
        self.assertEqual(scenario, DEFAULT_SCENARIO)
        self.assertEqual(hash(scenario), hash(DEFAULT_SCENARIO))
        with self.assertRaises(FrozenInstanceError):
            scenario.budget = 100

    def test_state_validation(self) -> None:
        scenario = DEFAULT_SCENARIO
        sites = sorted(scenario.buildable_cells)
        scenario.validate_state(TowerConfiguration())
        # 225 + 175 + 100 = exactly the 500-credit budget.
        scenario.validate_state(TowerConfiguration(tuple(
            Placement(tower_id, site)
            for tower_id, site in zip(TowerId, sites)
        )))
        scenario.validate_state(TowerConfiguration(tuple(
            Placement(TowerId.ARROW, site) for site in sites[:4]
        )))
        invalid_states = (
            TowerConfiguration((Placement(TowerId.ARROW, (2, 0)),)),
            TowerConfiguration((Placement(TowerId.ARROW, (99, 99)),)),
            TowerConfiguration(tuple(
                Placement(TowerId.ARROW, site) for site in sites[:5]
            )),
            TowerConfiguration(tuple(
                Placement(TowerId.SNIPER, site) for site in sites[:3]
            )),
        )
        for state in invalid_states:
            with self.subTest(state=state), self.assertRaises(ValueError):
                scenario.validate_state(state)


class DomainTests(unittest.TestCase):
    def test_invalid_tower_definition_values(self) -> None:
        tower = DEFAULT_SCENARIO.towers[0]
        invalid = {
            "id": ["arrow", "unknown", None], "name": ["", " ", 5],
            "cost": [0, -1, 1.5, True], "damage": [0, -1, True],
            "range": [0, -1, float("nan"), float("inf"), "2", True],
            "cooldown": [0, -1, float("nan"), float("inf"), True],
        }
        for name, values in invalid.items():
            for value in values:
                with self.subTest(name=name, value=value):
                    with self.assertRaises(ValueError):
                        replace(tower, **{name: value})

    def test_invalid_placement_values(self) -> None:
        for tower_id in ("arrow", "unknown", None, 1):
            with self.subTest(tower_id=tower_id), self.assertRaises(ValueError):
                Placement(tower_id, (1, 2))
        for cell in ((-1, 0), (0, -1), (True, 0), (1.5, 0),
                     (0,), (0, 1, 2), "01", None):
            with self.subTest(cell=cell), self.assertRaises(ValueError):
                Placement(TowerId.ARROW, cell)
        with self.assertRaises(ValueError):
            DEFAULT_SCENARIO.tower("arrow")

    def test_canonical_equality_hash_and_display(self) -> None:
        a = Placement(TowerId.ARROW, (1, 2))
        b = Placement(TowerId.CANNON, (4, 8))
        first = TowerConfiguration((a, b))
        second = TowerConfiguration((b, a))
        self.assertEqual(first, second)
        self.assertEqual(hash(first), hash(second))
        self.assertEqual(len({first, second}), 1)
        self.assertEqual({first: "cached"}[second], "cached")
        self.assertEqual(str(second), "arrow@(1, 2); cannon@(4, 8)")
        self.assertEqual(str(TowerConfiguration()), "<empty>")
        self.assertNotEqual(first, TowerConfiguration((a,)))
        self.assertNotEqual(TowerConfiguration((a,)), TowerConfiguration((
            Placement(TowerId.SNIPER, a.cell),
        )))

    def test_duplicate_cells_and_invalid_members_rejected(self) -> None:
        a = Placement(TowerId.ARROW, (1, 2))
        for items in ((a, a), (a, Placement(TowerId.CANNON, a.cell)), ("arrow",)):
            with self.subTest(items=items), self.assertRaises(ValueError):
                TowerConfiguration(items)

    def test_placement_and_state_are_immutable(self) -> None:
        cell = [1, 2]
        placement = Placement(TowerId.ARROW, cell)
        items = [placement]
        state = TowerConfiguration(items)
        cell[0] = 9
        items.clear()
        self.assertEqual(state.placements, (Placement(TowerId.ARROW, (1, 2)),))
        with self.assertRaises(FrozenInstanceError):
            placement.tower_id = TowerId.CANNON
        with self.assertRaises(FrozenInstanceError):
            state.placements = ()
        with self.assertRaises(FrozenInstanceError):
            DEFAULT_SCENARIO.towers[0].damage = 999
