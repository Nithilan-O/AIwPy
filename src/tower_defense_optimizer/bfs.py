"""1. BFS

Iterative breadth-first search orders states by number of tower placements, not
defense score. Every unique expanded configuration is evaluated as a possible
stopping point. Even a perfect defense does not stop exploration. The finite
frontier and visited set can require substantial memory; use SearchLimits.

Short helpers handle successors and classroom text rendering; bfs() owns the
FIFO loop. Stored immutable configurations are never modified. Trace stages
are expansion order, not a single solution path or simulator time steps.
"""

from collections import deque

from .actions import PlacementAction, apply_action, legal_actions
from .config import DEFAULT_SCENARIO
from .domain import Scenario, TowerConfiguration, TowerId
from .search_common import (
    AlgorithmName,
    ExpansionTracker,
    RunInstrumentation,
    SearchEvaluator,
    SearchLimitReached,
    SearchLimits,
    SearchResult,
    TerminationReason,
    TraceBuffer,
    check_time_limit,
)


QueueEntry = tuple[TowerConfiguration, PlacementAction | None, int]


def _enqueue_successors(
    state: TowerConfiguration,
    depth: int,
    frontier: deque[QueueEntry],
    visited: set[TowerConfiguration],
    scenario: Scenario,
    limits: SearchLimits,
    metrics: RunInstrumentation,
) -> None:
    """Discover once on enqueue, preserving the shared stable action order."""
    check_time_limit(limits, metrics.elapsed_seconds)
    for action in legal_actions(state, scenario):
        check_time_limit(limits, metrics.elapsed_seconds)
        successor = apply_action(state, action, scenario)
        if successor not in visited:
            visited.add(successor)
            frontier.append((successor, action, depth + 1))


_TOWER_SYMBOLS = {TowerId.ARROW: "A", TowerId.CANNON: "C", TowerId.SNIPER: "N"}


def render_configuration(state: TowerConfiguration, scenario: Scenario) -> str:
    """Render a validated configuration as labelled grid rows, without mutation."""
    scenario.validate_state(state)
    grid = [["." for _ in range(scenario.columns)] for _ in range(scenario.rows)]
    for row, column in scenario.buildable_cells:
        grid[row][column] = "+"
    for row, column in scenario.path:
        grid[row][column] = "#"
    for cell, symbol in ((scenario.path[0], "S"), (scenario.path[-1], "B")):
        grid[cell[0]][cell[1]] = symbol
    for placement in state.placements:
        grid[placement.cell[0]][placement.cell[1]] = _TOWER_SYMBOLS[placement.tower_id]
    header = "   " + " ".join(str(column) for column in range(scenario.columns))
    return "\n".join([header] + [
        f"{row:2} " + " ".join(cells) for row, cells in enumerate(grid)
    ])


def format_teaching_trace(result: SearchResult, scenario: Scenario) -> str:
    """Format only retained expansion steps; no further simulation or search."""
    if result.algorithm is not AlgorithmName.BFS:
        raise ValueError("a BFS result is required")
    legend = ", ".join(
        f"{_TOWER_SYMBOLS[tower_id]}={scenario.tower(tower_id).name}"
        for tower_id in TowerId
    )
    lines = ["1. BFS", "S=spawn, B=base, #=path, +=free build site, .=other cell",
             legend, "Path: " + " -> ".join(str(cell) for cell in scenario.path)]
    for stage, step in enumerate(result.trace):
        action = (f"{step.action.tower_type_id.value}@{step.action.cell_id}"
                  if step.action else "initial configuration")
        lines.extend(["", f"Stage {stage}", f"Depth {step.depth}; action: {action}",
                      render_configuration(step.configuration, scenario),
                      f"Defeated: {step.outcome[0]}; base health: {step.outcome[1]}"])
    if not result.trace:
        lines.append("No retained expansion stages (trace disabled or no states expanded).")
    if result.trace_steps_dropped:
        lines.append(f"Trace truncated: {result.trace_steps_dropped} expansion stages omitted.")
    lines.append(f"Termination: {result.termination_reason.value}; "
                 f"states explored: {result.states_explored}")
    return "\n".join(lines)


def bfs(
    scenario: Scenario = DEFAULT_SCENARIO, limits: SearchLimits = SearchLimits()
) -> SearchResult:
    """Search from the empty configuration until exhaustion or a resource limit.

    Follow the common measurement boundary exactly: initialize and evaluate the
    fallback inside instrumentation, construct SearchResult after exit. The empty
    fallback is evaluated once even with zero limits; it appears as Stage 0 only
    if admitted for expansion. Time checks are cooperative, including successor
    generation. A completed simulation can improve best-so-far past a deadline
    before the next check reports TIME_LIMIT. Objective ties retain the first.
    """
    with RunInstrumentation() as metrics:
        evaluator = SearchEvaluator(scenario)
        tracker = ExpansionTracker(limits)
        trace = TraceBuffer(limits.max_trace_steps)
        initial = TowerConfiguration()
        initial_outcome = evaluator.evaluate(initial)
        frontier: deque[QueueEntry] = deque([(initial, None, 0)])
        visited = {initial}
        reason = TerminationReason.EXHAUSTED
        try:
            while frontier:
                state, action, depth = frontier.popleft()
                if not tracker.admit(state, metrics.elapsed_seconds):
                    continue
                # Admission checks time immediately before evaluation. Reuse the
                # initial fallback outcome rather than simulate it a second time.
                outcome = initial_outcome if depth == 0 else evaluator.evaluate(state)
                trace.append(evaluator.trace_step(state, action, depth, outcome))
                _enqueue_successors(state, depth, frontier, visited,
                                    scenario, limits, metrics)
        except SearchLimitReached as stopped:
            reason = stopped.reason

    assert evaluator.best_configuration is not None and evaluator.best_outcome is not None
    return SearchResult(
        algorithm=AlgorithmName.BFS,
        best_configuration=evaluator.best_configuration,
        simulation_result=evaluator.best_outcome,
        elapsed_seconds=metrics.elapsed_seconds,
        states_explored=tracker.states_explored,
        peak_memory_bytes=metrics.peak_memory_bytes,
        termination_reason=reason,
        trace=trace.steps,
        trace_limit=limits.max_trace_steps,
        trace_steps_dropped=trace.dropped_steps,
    )
