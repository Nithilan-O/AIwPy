"""Deterministic combat, timing, trace, and complete-wave accounting tests."""

import unittest
from dataclasses import FrozenInstanceError, replace
from fractions import Fraction

from tower_defense_optimizer.config import DEFAULT_SCENARIO
from tower_defense_optimizer.domain import Placement, TowerConfiguration, TowerId
from tower_defense_optimizer.simulator import (
    EventKind,
    SimulationResult,
    _Enemy,
    _select_target,
    simulate,
)


def small_scenario(**changes):
    """Short straight path with controlled combat values, retaining all three IDs."""
    scenario = replace(
        DEFAULT_SCENARIO,
        path=((0, 0), (0, 1), (0, 2), (0, 3), (0, 4)),
        buildable_cells={(1, 0), (1, 1), (1, 2)},
        towers=tuple(replace(tower, range=10, damage=10, cooldown=1)
                     for tower in DEFAULT_SCENARIO.towers),
        enemy_count=3, enemy_health=10, tick_seconds=1,
        spawn_interval_seconds=1,
    )
    return replace(scenario, **changes)


def one_tower(cell=(1, 0)):
    return TowerConfiguration((Placement(TowerId.ARROW, cell),))


class SimulatorTests(unittest.TestCase):
    def test_no_towers_default_wave_and_health_clamping(self) -> None:
        result = simulate(TowerConfiguration(), DEFAULT_SCENARIO)
        self.assertEqual((result.enemies_defeated, result.enemies_escaped,
                          result.base_health_remaining), (0, 20, 0))
        spawns = [e for e in result.events if e.kind is EventKind.SPAWN]
        escapes = [e for e in result.events if e.kind is EventKind.ESCAPE]
        self.assertEqual([e.tick for e in spawns], list(range(0, 200, 10)))
        self.assertEqual([e.tick for e in escapes], list(range(140, 340, 10)))
        self.assertEqual([e.enemy_id for e in escapes], list(range(20)))
        self.assertTrue(all(e.position == (7.0, 9.0) for e in escapes))
        self.assertTrue(all(0 <= e.base_health_remaining <= DEFAULT_SCENARIO.base_health
                            for e in result.events))

    def test_known_effective_configuration(self) -> None:
        scenario = small_scenario()
        result = simulate(one_tower(), scenario)
        self.assertEqual((result.enemies_defeated, result.enemies_escaped,
                          result.base_health_remaining), (3, 0, scenario.base_health))
        defeats = [e for e in result.events if e.kind is EventKind.DEFEAT]
        self.assertEqual([(e.tick, e.enemy_id) for e in defeats], [(0, 0), (1, 1), (2, 2)])

    def test_default_configuration_is_effective(self) -> None:
        state = TowerConfiguration(tuple(
            Placement(TowerId.ARROW, cell)
            for cell in ((1, 2), (3, 4), (4, 6), (6, 8))
        ))
        result = simulate(state, DEFAULT_SCENARIO)
        self.assertEqual((result.enemies_defeated, result.enemies_escaped,
                          result.base_health_remaining), (20, 0, 10))
        self.assertEqual(result.enemies_defeated + result.enemies_escaped, 20)
        self.assertEqual(result.base_health_remaining,
                         max(0, DEFAULT_SCENARIO.base_health - result.enemies_escaped))

    def test_furthest_target_and_id_tie_rule(self) -> None:
        path = small_scenario().path
        # Equal progress cannot naturally occur with identical speeds and spaced
        # spawns; synthetic candidates directly exercise the documented tie rule.
        enemies = [_Enemy(5, 0, 10, Fraction(2)),
                   _Enemy(1, 0, 10, Fraction(2)),
                   _Enemy(0, 0, 10, Fraction(1)),
                   _Enemy(9, 0, 0, Fraction(3))]
        for order in (enemies, enemies[::-1]):
            target = _select_target(order, (1, 0), Fraction(10), path)
            self.assertEqual(target.id, 1)
        self.assertIsNone(_select_target(enemies, (9, 9), Fraction(1), path))
        scenario = small_scenario(enemy_health=1000)
        result = simulate(one_tower(), scenario)
        shots = [e for e in result.events if e.kind is EventKind.SHOT]
        self.assertEqual(next(e.enemy_id for e in shots if e.tick == 2), 0)

    def test_tower_order_immediate_damage_and_no_splash(self) -> None:
        scenario = small_scenario(enemy_health=15)
        state = TowerConfiguration((Placement(TowerId.ARROW, (1, 1)),
                                    Placement(TowerId.ARROW, (1, 0))))
        result = simulate(state, scenario)
        tick_zero = [e for e in result.events if e.tick == 0]
        self.assertEqual([e.kind for e in tick_zero],
                         [EventKind.SPAWN, EventKind.SHOT,
                          EventKind.SHOT, EventKind.DEFEAT])
        self.assertEqual([e.tower_cell for e in tick_zero[1:3]], [(1, 0), (1, 1)])
        self.assertEqual([e.enemy_health for e in tick_zero[1:3]], [5, 0])
        self.assertEqual(result.enemies_defeated, 3)

    def test_cooldown_rounds_up_and_no_timing_drift(self) -> None:
        scenario = small_scenario(enemy_count=1, enemy_health=1000, tick_seconds=0.1)
        scenario = replace(scenario, towers=tuple(
            replace(tower, cooldown=0.25) for tower in scenario.towers
        ))
        result = simulate(one_tower(), scenario)
        shots = [e.tick for e in result.events if e.kind is EventKind.SHOT]
        self.assertEqual(shots, list(range(0, 40, 3)))
        self.assertEqual(result.enemies_escaped, 1)

    def test_killed_target_is_not_shot_again_and_damage_has_no_splash(self) -> None:
        scenario = small_scenario(enemy_count=4)
        scenario = replace(scenario, towers=tuple(
            replace(tower, cooldown=3) for tower in scenario.towers
        ))
        state = TowerConfiguration((Placement(TowerId.ARROW, (1, 0)),
                                    Placement(TowerId.ARROW, (1, 1))))
        result = simulate(state, scenario)
        shots = [e for e in result.events if e.kind is EventKind.SHOT]
        self.assertEqual([(e.tick, e.enemy_id, e.tower_cell) for e in shots],
                         [(0, 0, (1, 0)), (1, 1, (1, 1)),
                          (3, 2, (1, 0)), (4, 3, (1, 1))])
        self.assertEqual(result.enemies_defeated, 4)

    def test_range_boundary_and_idle_ready_tower(self) -> None:
        scenario = small_scenario(enemy_count=1)
        scenario = replace(scenario, towers=tuple(
            replace(tower, range=1, cooldown=3) for tower in scenario.towers
        ))
        result = simulate(one_tower((1, 2)), scenario)
        shots = [e for e in result.events if e.kind is EventKind.SHOT]
        self.assertEqual([(e.tick, e.position) for e in shots], [(2, (0.0, 2.0))])
        self.assertEqual(result.enemies_defeated, 1)

    def test_escapes_before_fire_and_movement_event_order(self) -> None:
        scenario = small_scenario(
            enemy_count=1, path=((0, 0), (0, 1)), buildable_cells={(1, 1)},
        )
        scenario = replace(scenario, towers=tuple(
            replace(tower, range=1) for tower in scenario.towers
        ))
        result = simulate(one_tower((1, 1)), scenario)
        self.assertEqual([e.kind for e in result.events],
                         [EventKind.SPAWN, EventKind.MOVE, EventKind.ESCAPE])
        self.assertEqual(result.enemies_escaped, 1)
        self.assertEqual(result.base_health_remaining, scenario.base_health - 1)

    def test_nonintegral_spawn_spacing_and_path_interpolation(self) -> None:
        scenario = small_scenario(tick_seconds=0.2, spawn_interval_seconds=0.3)
        result = simulate(TowerConfiguration(), scenario)
        self.assertEqual([e.tick for e in result.events if e.kind is EventKind.SPAWN],
                         [0, 2, 3])
        first_move = next(e for e in result.events if e.kind is EventKind.MOVE)
        self.assertEqual((first_move.tick, first_move.position), (1, (0.0, 0.2)))

    def test_large_leak_damage_and_complete_accounting_after_base_destroyed(self) -> None:
        scenario = small_scenario(base_health=2, leak_damage=5)
        result = simulate(TowerConfiguration(), scenario)
        self.assertEqual(result.base_health_remaining, 0)
        self.assertEqual(result.enemies_escaped, scenario.enemy_count)
        self.assertTrue(all(e.base_health_remaining >= 0 for e in result.events))

    def test_repeatability_input_preservation_and_result_immutability(self) -> None:
        scenario = small_scenario()
        state = one_tower()
        before = (hash(state), hash(scenario))
        first = simulate(state, scenario)
        second = simulate(state, scenario)
        self.assertEqual(first, second)
        self.assertEqual(hash(first), hash(second))
        self.assertEqual(before, (hash(state), hash(scenario)))
        self.assertEqual(first, simulate(state, replace(scenario,
                         towers=scenario.towers[::-1])))
        with self.assertRaises(FrozenInstanceError):
            first.enemies_defeated = 0
        with self.assertRaises(FrozenInstanceError):
            first.events[0].tick = 99

    def test_short_deadline_rejected_and_exact_deadline_accepted(self) -> None:
        scenario = small_scenario(max_wave_seconds=6)
        result = simulate(TowerConfiguration(), scenario)
        self.assertEqual(result.events[-1].tick, 6)
        with self.assertRaises(ValueError):
            simulate(TowerConfiguration(), replace(scenario, max_wave_seconds=5.9))
        with self.assertRaises(ValueError):
            simulate(TowerConfiguration((Placement(TowerId.ARROW, (9, 9)),)), scenario)

    def test_result_rejects_invalid_counts(self) -> None:
        for counts in ((-1, 0, 0), (0, -1, 0), (0, 0, -1), (True, 0, 0)):
            with self.subTest(counts=counts), self.assertRaises(ValueError):
                SimulationResult(*counts)
