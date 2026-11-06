"""Shared deterministic placement and transition contract.

Stopping is a caller decision, permitted for every valid configuration. It is
not a placement edge or a self-loop in the configuration graph.
"""

from dataclasses import dataclass

from .domain import Cell, Placement, Scenario, TowerConfiguration, TowerId


@dataclass(frozen=True, slots=True)
class PlacementAction:
    """Place a tower; cell_id uses the existing (row, column) cell identity."""

    cell_id: Cell
    tower_type_id: TowerId

    def __post_init__(self) -> None:
        placement = Placement(self.tower_type_id, self.cell_id)
        object.__setattr__(self, "cell_id", placement.cell)


def budget_used(state: TowerConfiguration, scenario: Scenario) -> int:
    """Return credits spent for legality/explanation, never ranking or scoring.

    Invalid configurations raise ValueError, as in all public helpers here.
    """
    scenario.validate_state(state)
    return sum(scenario.tower(item.tower_id).cost for item in state.placements)


def legal_actions(
    state: TowerConfiguration, scenario: Scenario
) -> tuple[PlacementAction, ...]:
    """Generate all legal placements, ordered by row, column, then tower ID.

    This is the sole placement-legality generator. Ordering is independent of
    catalog order, input placement order, and set iteration; cost is not a key.
    """
    spent = budget_used(state, scenario)
    if len(state.placements) >= scenario.max_towers:
        return ()
    occupied = {item.cell for item in state.placements}
    towers = sorted(scenario.towers, key=lambda tower: tower.id.value)
    return tuple(
        PlacementAction(cell, tower.id)
        for cell in sorted(scenario.buildable_cells - occupied)
        for tower in towers
        if spent + tower.cost <= scenario.budget
    )


def apply_action(
    state: TowerConfiguration, action: PlacementAction, scenario: Scenario
) -> TowerConfiguration:
    """Validate through legal_actions and return a new canonical configuration."""
    if not isinstance(action, PlacementAction):
        raise ValueError("action must be a PlacementAction")
    if action not in legal_actions(state, scenario):
        raise ValueError("placement action is not legal for this state and scenario")
    return TowerConfiguration(state.placements + (
        Placement(action.tower_type_id, action.cell_id),
    ))


def can_stop(state: TowerConfiguration, scenario: Scenario) -> bool:
    """Every valid state is eligible as a final configuration, at any depth."""
    scenario.validate_state(state)
    return True


def is_terminal(state: TowerConfiguration, scenario: Scenario) -> bool:
    """True when no placement can extend this state; stopping remains optional earlier."""
    return not legal_actions(state, scenario)
