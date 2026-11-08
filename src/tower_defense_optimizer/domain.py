"""Immutable domain values; scenario defaults live exclusively in config.py."""

from dataclasses import dataclass
from enum import Enum
from math import isfinite


class TowerId(str, Enum):
    ARROW = "arrow"
    CANNON = "cannon"
    SNIPER = "sniper"


Cell = tuple[int, int]  # (row, column), zero based


def _integer(name: str, value: int, minimum: int = 1) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


def _positive(name: str, value: float) -> None:
    if type(value) not in (int, float) or not isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number")


def _cell(value: Cell) -> Cell:
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ValueError("Cell must contain a row and column")
    row, column = value
    _integer("Row", row, 0)
    _integer("Column", column, 0)
    return row, column


@dataclass(frozen=True, slots=True)
class TowerDefinition:
    id: TowerId
    name: str
    cost: int
    range: float  # grid cells
    damage: int
    cooldown: float  # seconds

    def __post_init__(self) -> None:
        if not isinstance(self.id, TowerId):
            raise ValueError("Tower id must be a TowerId")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Tower name must be non-empty")
        _integer("Cost", self.cost)
        _integer("Damage", self.damage)
        _positive("Range", self.range)
        _positive("Cooldown", self.cooldown)


@dataclass(frozen=True, slots=True)
class Placement:
    tower_id: TowerId
    cell: Cell

    def __post_init__(self) -> None:
        if not isinstance(self.tower_id, TowerId):
            raise ValueError("Tower ID must be a TowerId")
        object.__setattr__(self, "cell", _cell(self.cell))


@dataclass(frozen=True, slots=True)
class TowerConfiguration:
    """Canonical placement tuple, independent of construction order.

    Structural validity is enforced here. Use Scenario.validate_state() for
    scenario-dependent build-site, budget, and tower-count constraints.
    """

    placements: tuple[Placement, ...] = ()

    def __post_init__(self) -> None:
        placements = tuple(self.placements)
        if any(not isinstance(item, Placement) for item in placements):
            raise ValueError("Placements must contain Placement values")
        if len({item.cell for item in placements}) != len(placements):
            raise ValueError("Only one tower may occupy a cell")
        object.__setattr__(
            self,
            "placements",
            tuple(
                sorted(placements, key=lambda item: (item.cell, item.tower_id.value))
            ),
        )

    def __str__(self) -> str:
        return (
            "; ".join(
                f"{item.tower_id.value}@({item.cell[0]}, {item.cell[1]})"
                for item in self.placements
            )
            or "<empty>"
        )


@dataclass(frozen=True, slots=True)
class Scenario:
    rows: int
    columns: int
    path: tuple[Cell, ...]  # ordered spawn to base, including both endpoints
    buildable_cells: frozenset[Cell]
    towers: tuple[TowerDefinition, ...]
    enemy_count: int
    enemy_health: int
    enemy_speed: float  # path cells per second
    leak_damage: int  # base health lost per enemy reaching the base
    budget: int
    max_towers: int
    base_health: int
    tick_seconds: float
    spawn_interval_seconds: float
    max_wave_seconds: float

    def __post_init__(self) -> None:
        for name in (
            "rows",
            "columns",
            "enemy_count",
            "enemy_health",
            "leak_damage",
            "max_towers",
            "base_health",
        ):
            _integer(name.replace("_", " ").capitalize(), getattr(self, name))
        _integer("Budget", self.budget, 0)
        for name in (
            "enemy_speed",
            "tick_seconds",
            "spawn_interval_seconds",
            "max_wave_seconds",
        ):
            _positive(name.replace("_", " ").capitalize(), getattr(self, name))
        if self.tick_seconds > min(self.spawn_interval_seconds, self.max_wave_seconds):
            raise ValueError("Tick must not exceed spawn interval or wave limit")

        path = tuple(_cell(cell) for cell in self.path)
        buildable = frozenset(_cell(cell) for cell in self.buildable_cells)
        towers = tuple(self.towers)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "buildable_cells", buildable)
        object.__setattr__(self, "towers", towers)

        if len(path) < 2 or path[0] == path[-1]:
            raise ValueError("Path must have distinct spawn and base endpoints")
        if len(set(path)) != len(path):
            raise ValueError("Path must not repeat cells")
        if any(not self.contains(cell) for cell in (*path, *buildable)):
            raise ValueError("Path and buildable cells must be in bounds")
        if any(
            abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1 for a, b in zip(path, path[1:])
        ):
            raise ValueError("Path must be orthogonally contiguous")
        if not buildable or buildable.intersection(path):
            raise ValueError("Buildable cells must be non-empty and off the path")
        if any(not isinstance(tower, TowerDefinition) for tower in towers):
            raise ValueError("Towers must contain TowerDefinition values")
        if len(towers) != len(TowerId) or {t.id for t in towers} != set(TowerId):
            raise ValueError("Define exactly one tower for each TowerId")
        if len({t.name for t in towers}) != len(towers):
            raise ValueError("Tower names must be distinct")

    def contains(self, cell: Cell) -> bool:
        return 0 <= cell[0] < self.rows and 0 <= cell[1] < self.columns

    def tower(self, tower_id: TowerId) -> TowerDefinition:
        if not isinstance(tower_id, TowerId):
            raise ValueError("Tower ID must be a TowerId")
        return next(tower for tower in self.towers if tower.id is tower_id)

    def validate_state(self, state: TowerConfiguration) -> None:
        """Raise ValueError for a configuration that cannot be built here."""
        if not isinstance(state, TowerConfiguration):
            raise ValueError("State must be a TowerConfiguration")
        if len(state.placements) > self.max_towers:
            raise ValueError("Tower count exceeds scenario limit")
        if any(item.cell not in self.buildable_cells for item in state.placements):
            raise ValueError("Tower must occupy a buildable cell")
        if (
            sum(self.tower(item.tower_id).cost for item in state.placements)
            > self.budget
        ):
            raise ValueError("Tower cost exceeds scenario budget")
