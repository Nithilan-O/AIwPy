"""Single source of truth for the fixed demonstration scenario."""

from .domain import Scenario, TowerDefinition, TowerId


DEFAULT_SCENARIO = Scenario(
    rows=10,
    columns=10,
    path=(
        (2, 0), (2, 1), (2, 2), (2, 3), (2, 4), (2, 5), (2, 6), (2, 7),
        (3, 7), (4, 7), (5, 7), (6, 7), (7, 7), (7, 8), (7, 9),
    ),
    buildable_cells=frozenset({
        (1, 2), (3, 4), (1, 6), (4, 6), (4, 8), (6, 6), (6, 8), (8, 9),
    }),
    towers=(
        TowerDefinition(TowerId.ARROW, "Arrow", 100, 2.5, 12, 0.5),
        TowerDefinition(TowerId.CANNON, "Cannon", 175, 2.0, 30, 1.5),
        TowerDefinition(TowerId.SNIPER, "Sniper", 225, 4.0, 45, 2.0),
    ),
    enemy_count=20,
    enemy_health=100,
    enemy_speed=1.0,
    leak_damage=1,
    budget=500,
    max_towers=4,
    base_health=10,
    tick_seconds=0.1,
    spawn_interval_seconds=1.0,
    max_wave_seconds=60.0,
)
