"""3. Simple Hill Climbing

Inspect all legal one-placement neighbors, then accept only a strict gameplay
improvement. This iterative best-neighbor variant can stop on plateaus and makes
no global-optimum claim. Short helpers handle deterministic ties and teaching text.
"""

from dataclasses import dataclass

from .actions import PlacementAction, apply_action, legal_actions
from .bfs import render_configuration
from .config import DEFAULT_SCENARIO
from .domain import Scenario, TowerConfiguration
from .evaluation import objective_key
from .search_common import (
    AlgorithmName, ExpansionTracker, RunInstrumentation, SearchEvaluator,
    SearchLimitReached, SearchLimits, SearchResult, TerminationReason, TraceBuffer,
    TraceStep, check_time_limit,
)


@dataclass(frozen=True, slots=True)
class HillClimbingStep(TraceStep):
    """One accepted state and a compact summary of its outgoing comparison.

    A partial scan is diagnostic only: it never authorizes a move. No neighbor
    simulator logs or unbounded lists are retained. Compatible with TraceStep.
    """

    neighbor_configuration: TowerConfiguration | None = None
    neighbor_action: PlacementAction | None = None
    neighbor_outcome: tuple[int, int] | None = None
    neighbors_evaluated: int = 0
    scan_complete: bool = False
    decision: str = ""


def _tie_key(state: TowerConfiguration, action: PlacementAction) -> tuple:
    """Canonical state, then action; never spending or catalog/generator order."""
    return (tuple((item.cell, item.tower_id.value) for item in state.placements),
            action.cell_id, action.tower_type_id.value)


def _prefer(candidate: tuple, incumbent: tuple | None) -> bool:
    """Maximize shared gameplay key; minimize canonical state/action on ties."""
    if incumbent is None:
        return True
    state, action, outcome = candidate
    old_state, old_action, old_outcome = incumbent
    return (objective_key(outcome) > objective_key(old_outcome)
            or (objective_key(outcome) == objective_key(old_outcome)
                and _tie_key(state, action) < _tie_key(old_state, old_action)))


def hill_climbing(
    scenario: Scenario = DEFAULT_SCENARIO, limits: SearchLimits = SearchLimits()
) -> SearchResult:
    """Return the current accepted best, including on an interrupted neighbor scan.

    Count unique states admitted for expansion, not evaluated-only neighbors.
    Evaluate the empty fallback even with zero limits. A complete neighborhood is
    required before moving; a time-interrupted scan returns the current state.
    Accepted states awaiting admission can be returned/traced without being counted
    as explored. All search/simulation/trace work uses the BFS/A* measurement scope.
    """
    with RunInstrumentation() as metrics:
        evaluator = SearchEvaluator(scenario)
        tracker = ExpansionTracker(limits)
        trace = TraceBuffer(limits.max_trace_steps)
        current = TowerConfiguration()
        outcome = evaluator.evaluate(current)
        incoming = None
        depth = 0
        reason = TerminationReason.LOCAL_OPTIMUM
        while True:
            neighbor = None
            evaluated = 0
            complete = False
            admitted = False
            try:
                tracker.admit(current, metrics.elapsed_seconds)
                admitted = True
                check_time_limit(limits, metrics.elapsed_seconds)
                for action in legal_actions(current, scenario):
                    check_time_limit(limits, metrics.elapsed_seconds)
                    state = apply_action(current, action, scenario)
                    check_time_limit(limits, metrics.elapsed_seconds)
                    candidate = (state, action, evaluator.evaluate(state))
                    evaluated += 1
                    if _prefer(candidate, neighbor):
                        neighbor = candidate
                check_time_limit(limits, metrics.elapsed_seconds)
                complete = True
                improves = (neighbor is not None
                            and objective_key(neighbor[2]) > objective_key(outcome))
                if improves:
                    decision = "Accept best neighbor: strict gameplay improvement."
                elif neighbor is None:
                    decision = "Stop: no legal neighbor (local optimum)."
                else:
                    decision = "Stop: best neighbor is equal or worse; no strict improvement."
            except SearchLimitReached as stopped:
                reason = stopped.reason
                improves = False
                decision = f"Stop: resource limit {reason.value}; retain current accepted state."

            # Initial fallback is untraced at zero allowance, as in BFS/A*.
            # Every accepted move still has a stage if its next admission fails.
            if admitted or depth > 0:
                trace.append(HillClimbingStep(
                    configuration=current, action=incoming, depth=depth,
                    outcome=objective_key(outcome),
                    neighbor_configuration=neighbor[0] if neighbor else None,
                    neighbor_action=neighbor[1] if neighbor else None,
                    neighbor_outcome=objective_key(neighbor[2]) if neighbor else None,
                    neighbors_evaluated=evaluated, scan_complete=complete,
                    decision=decision,
                ))
            if not improves:
                break
            current, incoming, outcome = neighbor
            depth += 1

    return SearchResult(
        algorithm=AlgorithmName.HILL_CLIMBING,
        best_configuration=current, simulation_result=outcome,
        elapsed_seconds=metrics.elapsed_seconds,
        states_explored=tracker.states_explored,
        peak_memory_bytes=metrics.peak_memory_bytes, termination_reason=reason,
        trace=trace.steps, trace_limit=limits.max_trace_steps,
        trace_steps_dropped=trace.dropped_steps,
    )


def format_teaching_trace(result: SearchResult, scenario: Scenario) -> str:
    """Render accepted states and bounded best-neighbor comparison summaries."""
    if result.algorithm is not AlgorithmName.HILL_CLIMBING:
        raise ValueError("a Simple Hill Climbing result is required")
    lines = [
        "3. Simple Hill Climbing", "Initial configuration: empty (no towers).",
        "Maximize (defeated, base health); accept only strict improvement.",
        "Ties: smallest canonical state, then action (cell, tower ID).",
        "S=spawn, B=base, #=path, +=free build site, .=other cell",
        "A=Arrow, C=Cannon, N=Sniper",
        "Path: " + " -> ".join(str(cell) for cell in scenario.path),
    ]
    previous = None
    for stage, step in enumerate(result.trace):
        action = (f"{step.action.tower_type_id.value}@{step.action.cell_id}"
                  if step.action else "initial configuration")
        lines.extend(["", f"Stage {stage}", f"Depth {step.depth}; action: {action}",
                      render_configuration(step.configuration, scenario),
                      f"Current outcome (defeated, base health): {step.outcome}"])
        if previous is not None:
            lines.append(f"Move accepted: {step.outcome} > {previous} (strict improvement).")
        previous = step.outcome
        if isinstance(step, HillClimbingStep):
            lines.append(f"Neighbors evaluated: {step.neighbors_evaluated}; "
                         f"complete scan: {step.scan_complete}")
            if step.neighbor_configuration is not None:
                lines.extend([
                    f"Best evaluated neighbor: {step.neighbor_action.tower_type_id.value}"
                    f"@{step.neighbor_action.cell_id}; "
                    f"outcome: {step.neighbor_outcome}",
                    render_configuration(step.neighbor_configuration, scenario),
                ])
            lines.append(step.decision)
    if not result.trace:
        lines.append("No retained stages (trace disabled or initial state not admitted).")
    if result.trace_steps_dropped:
        lines.append(f"Trace truncated: {result.trace_steps_dropped} accepted-state stages omitted.")
    lines.extend([
        f"Termination: {result.termination_reason.value}; states explored: {result.states_explored}",
        "Explored = unique states admitted for expansion; evaluated-only neighbors do not count.",
        "Returned current accepted best; no global optimum is implied.",
    ])
    return "\n".join(lines)
