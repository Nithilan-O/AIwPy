"""UI-independent presentation data and input validation; no Tk or search logic."""

from dataclasses import dataclass

from .application import format_report, format_trace
from .domain import Scenario, TowerConfiguration, TowerId
from .search_common import SearchLimits, SearchResult


ALGORITHM_LABELS = {
    "BFS": "bfs", "A* Algorithm": "astar", "Simple Hill Climbing": "hill-climbing",
    "Compare all three": "all",
}
MEASURE_LABELS = (
    "Enemies defeated", "Enemies escaped", "Base health left",
    "Execution time (s)", "Explored states", "Memory (KiB)",
)
_SYMBOLS = {TowerId.ARROW: "A", TowerId.CANNON: "C", TowerId.SNIPER: "N"}


@dataclass(frozen=True)
class GridCell:
    row: int
    column: int
    kind: str
    symbol: str


@dataclass(frozen=True)
class ResultView:
    algorithm: str
    measures: tuple[str, ...]
    configuration: str
    termination: str
    explanation: str
    trace: str
    grid: tuple[GridCell, ...]


def parse_limits(expanded: str, seconds: str, trace_steps: str) -> SearchLimits:
    """Give field-specific errors; use shared validation for numeric semantics."""
    try:
        cap = int(expanded)
        if cap < 0:
            raise ValueError
    except ValueError as error:
        raise ValueError("Explored-state limit must be a whole number of at least 0.") from error
    try:
        steps = int(trace_steps)
        if not 0 <= steps <= 20:
            raise ValueError
    except ValueError as error:
        raise ValueError("Trace stages must be a whole number from 0 to 20.") from error
    try:
        deadline = float(seconds) if seconds.strip() else None
        return SearchLimits(cap, deadline, steps)
    except ValueError as error:
        raise ValueError("Time limit must be finite nonnegative seconds, or blank for none.") from error


def grid_cells(configuration: TowerConfiguration, scenario: Scenario) -> tuple[GridCell, ...]:
    """Translate a validated configuration to labelled tiles for drawing only."""
    scenario.validate_state(configuration)
    towers = {placement.cell: placement.tower_id for placement in configuration.placements}
    path = set(scenario.path)
    cells = []
    for row in range(scenario.rows):
        for column in range(scenario.columns):
            cell = (row, column)
            if cell in towers:
                kind, symbol = towers[cell].value, _SYMBOLS[towers[cell]]
            elif cell == scenario.path[0]:
                kind, symbol = "spawn", "S"
            elif cell == scenario.path[-1]:
                kind, symbol = "base", "B"
            elif cell in path:
                kind, symbol = "path", "#"
            elif cell in scenario.buildable_cells:
                kind, symbol = "buildable", "+"
            else:
                kind, symbol = "other", ""
            cells.append(GridCell(row, column, kind, symbol))
    return tuple(cells)


def result_view(result: SearchResult, scenario: Scenario, limits: SearchLimits) -> ResultView:
    """Format original shared results, preserving outcome/configuration pairing."""
    outcome = result.simulation_result
    configuration = "; ".join(
        f"{scenario.tower(p.tower_id).name} at {p.cell}"
        for p in result.best_configuration.placements
    ) or "Empty configuration (no towers)"
    return ResultView(
        algorithm=result.algorithm.value,
        measures=(str(outcome.enemies_defeated), str(outcome.enemies_escaped),
                  str(outcome.base_health_remaining), f"{result.elapsed_seconds:.6f}",
                  str(result.states_explored), f"{result.peak_memory_bytes / 1024:.2f}"),
        configuration=configuration,
        termination=result.termination_reason.value,
        explanation=format_report((result,), scenario, limits),
        trace=format_trace(result, scenario),
        grid=grid_cells(result.best_configuration, scenario),
    )
