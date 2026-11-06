"""Pure fixed-tick simulation shared by future search and presentation code."""

from dataclasses import dataclass
from enum import Enum
from fractions import Fraction
from math import ceil, floor

from .domain import Cell, Scenario, TowerConfiguration, TowerId


class EventKind(str, Enum):
    SPAWN = "spawn"
    MOVE = "move"
    SHOT = "shot"
    DEFEAT = "defeat"
    ESCAPE = "escape"


@dataclass(frozen=True, slots=True)
class SimulationEvent:
    tick: int
    kind: EventKind
    enemy_id: int
    progress: float
    position: tuple[float, float]
    enemy_health: int
    base_health_remaining: int
    tower_cell: Cell | None = None
    tower_type_id: TowerId | None = None


@dataclass(frozen=True, slots=True)
class SimulationResult:
    enemies_defeated: int
    enemies_escaped: int
    base_health_remaining: int
    events: tuple[SimulationEvent, ...] = ()

    def __post_init__(self) -> None:
        for value in (self.enemies_defeated, self.enemies_escaped,
                      self.base_health_remaining):
            if type(value) is not int or value < 0:
                raise ValueError("outcome counts and health must be nonnegative integers")
        events = tuple(self.events)
        if any(not isinstance(event, SimulationEvent) for event in events):
            raise ValueError("events must contain SimulationEvent values")
        object.__setattr__(self, "events", events)


@dataclass
class _Enemy:
    id: int
    spawn_tick: int
    health: int
    progress: Fraction = Fraction(0)


def _number(value: float) -> Fraction:
    """Use decimal input values exactly, avoiding accumulated binary time drift."""
    return Fraction(str(value))


def _position(progress: Fraction, path: tuple[Cell, ...]) -> tuple[Fraction, Fraction]:
    segment = min(floor(progress), len(path) - 1)
    start = path[segment]
    end = path[min(segment + 1, len(path) - 1)]
    offset = progress - segment
    return tuple(Fraction(a) + (b - a) * offset for a, b in zip(start, end))


def _select_target(
    enemies: list[_Enemy], cell: Cell, attack_range: Fraction, path: tuple[Cell, ...]
) -> _Enemy | None:
    candidates = []
    for enemy in enemies:
        row, column = _position(enemy.progress, path)
        distance_squared = (row - cell[0]) ** 2 + (column - cell[1]) ** 2
        if enemy.health > 0 and distance_squared <= attack_range ** 2:
            candidates.append(enemy)
    return min(candidates, key=lambda enemy: (-enemy.progress, enemy.id), default=None)


def simulate(configuration: TowerConfiguration, scenario: Scenario) -> SimulationResult:
    """Run one complete wave with local state and an immutable ordered event log.

    At tick 0 and each subsequent tick: spawn, move, escape, fire. Spawns and
    movement use enemy ID order; towers fire in canonical placement order.
    Cooldowns round up to whole ticks. An idle ready tower stays ready. Damage
    is immediate, single-target, and non-splash. Base destruction does not end
    the wave. See README for the full timing and timeout contract.
    """
    scenario.validate_state(configuration)
    tick_seconds = _number(scenario.tick_seconds)
    step = _number(scenario.enemy_speed) * tick_seconds
    path_length = len(scenario.path) - 1
    spawn_ticks = tuple(
        ceil(enemy_id * _number(scenario.spawn_interval_seconds) / tick_seconds)
        for enemy_id in range(scenario.enemy_count)
    )
    last_tick = spawn_ticks[-1] + ceil(path_length / step)
    if last_tick > floor(_number(scenario.max_wave_seconds) / tick_seconds):
        raise ValueError("wave time limit cannot accommodate all spawns and path travel")

    towers = tuple(scenario.tower(item.tower_id) for item in configuration.placements)
    cooldowns = tuple(ceil(_number(tower.cooldown) / tick_seconds) for tower in towers)
    ranges = tuple(_number(tower.range) for tower in towers)
    ready_ticks = [0] * len(towers)
    active: list[_Enemy] = []
    events: list[SimulationEvent] = []
    next_enemy = defeated = escaped = 0
    base_health = scenario.base_health

    def record(tick: int, kind: EventKind, enemy: _Enemy,
               tower_index: int | None = None) -> None:
        placement = (configuration.placements[tower_index]
                     if tower_index is not None else None)
        row, column = _position(enemy.progress, scenario.path)
        events.append(SimulationEvent(
            tick, kind, enemy.id, float(enemy.progress), (float(row), float(column)),
            enemy.health, base_health,
            placement.cell if placement else None,
            placement.tower_id if placement else None,
        ))

    for tick in range(last_tick + 1):
        while next_enemy < scenario.enemy_count and spawn_ticks[next_enemy] <= tick:
            enemy = _Enemy(next_enemy, tick, scenario.enemy_health)
            active.append(enemy)
            record(tick, EventKind.SPAWN, enemy)
            next_enemy += 1

        for enemy in active:
            if tick > enemy.spawn_tick:
                enemy.progress = min((tick - enemy.spawn_tick) * step, path_length)
                record(tick, EventKind.MOVE, enemy)
        for enemy in active:
            if enemy.progress >= path_length:
                escaped += 1
                base_health = max(0, base_health - scenario.leak_damage)
                record(tick, EventKind.ESCAPE, enemy)
        active = [enemy for enemy in active if enemy.progress < path_length]

        for index, placement in enumerate(configuration.placements):
            if tick < ready_ticks[index]:
                continue
            target = _select_target(active, placement.cell, ranges[index], scenario.path)
            if target is None:
                continue
            target.health = max(0, target.health - towers[index].damage)
            ready_ticks[index] = tick + cooldowns[index]
            record(tick, EventKind.SHOT, target, index)
            if target.health == 0:
                defeated += 1
                record(tick, EventKind.DEFEAT, target, index)
                active.remove(target)

        if next_enemy == scenario.enemy_count and not active:
            break

    assert defeated + escaped == scenario.enemy_count
    assert 0 <= base_health <= scenario.base_health
    return SimulationResult(defeated, escaped, base_health, tuple(events))
