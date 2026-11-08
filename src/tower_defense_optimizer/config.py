"""Contains the configuration of the board for the game."""

from .domain import Scenario, TowerDefinition, TowerId


DEFAULT_SCENARIO = Scenario(
    rows=10,
    columns=10,
    path=(
        (2, 0),
        (2, 1),
        (2, 2),
        (2, 3),
        (2, 4),
        (2, 5),
        (2, 6),
        (2, 7),
        (3, 7),
        (4, 7),
        (5, 7),
        (6, 7),
        (7, 7),
        (7, 8),
        (7, 9),
    ),  # The path which the enemies take inorder to reach the goal state
    buildable_cells=frozenset(
        {
            (1, 2),
            (3, 4),
            (1, 6),
            (4, 6),
            (4, 8),
            (6, 6),
            (6, 8),
            (8, 9),
        }
    ),  # All possible cells where towers can be placed
    towers=(
        TowerDefinition(TowerId.ARROW, "Arrow", 100, 2.5, 12, 0.5),
        TowerDefinition(TowerId.CANNON, "Cannon", 175, 2.0, 30, 1.5),
        TowerDefinition(TowerId.SNIPER, "Sniper", 225, 4.0, 45, 2.0),
    ),  # All the towers in the game
    enemy_count=20,  # Number of enemies
    enemy_health=75,  # Health per enemy
    enemy_speed=1.0,  # Enemy Speed
    leak_damage=1,  # The damage the player takes when the enemy reaches the base
    budget=500,  # The overall cost the the player has to defend their base
    max_towers=4,  # The limit on the towers placed on the field
    base_health=20,  # The health that the player has on the start of the game
    tick_seconds=0.1,
    spawn_interval_seconds=1.5,
    max_wave_seconds=60.0,
)
