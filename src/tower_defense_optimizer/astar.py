"""2. A* algorithm

Teaching A* traversal on placement depth, not defense quality. Unit placement
cost gives g = tower count; h = max(0, max_towers - g); f = g + h. The heuristic
is exact for reaching the fixed depth when a legal completion exists, and only
a depth lower bound when that depth is unreachable. Such dead ends still get
gameplay evaluation. All legal states have equal f, so stable insertion ties
produce BFS-like order on this graph. No gameplay optimality-first claim follows.

The heap retains multiple equal-f entries, best-known g is keyed by canonical
state, and outdated entries are skipped. Unlike a dictionary keyed by f, equal
priorities cannot overwrite states. Neither a depth goal nor a perfect defense
stops traversal: the recommendation is best among evaluated configurations only.
"""

from heapq import heappop, heappush
from itertools import count

from .actions import PlacementAction, apply_action, legal_actions
from .bfs import render_configuration
from .config import DEFAULT_SCENARIO
from .domain import Scenario, TowerConfiguration
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


def g_cost(state: TowerConfiguration) -> int:
    """Unit transition cost accumulated from the empty configuration."""
    return len(state.placements)


def heuristic(state: TowerConfiguration, scenario: Scenario) -> int:
    """Additional placements to target depth, conditional on legal reachability.

    This never estimates defense quality and does not prune unreachable states.
    """
    return max(0, scenario.max_towers - g_cost(state))


def is_target_depth(state: TowerConfiguration, scenario: Scenario) -> bool:
    """A fixed-depth goal has exactly max_towers placements and is scenario-valid."""
    scenario.validate_state(state)
    return g_cost(state) == scenario.max_towers


_Entry = tuple[int, int, int, TowerConfiguration, PlacementAction | None]


class _Frontier:
    """Min-heap with a unique sequence tie-breaker and best-g relaxation.

    All real routes to a canonical configuration have the same unit cost here;
    strict improvement/stale guards retain conventional A* bookkeeping anyway.
    """

    def __init__(self, scenario: Scenario) -> None:
        self._scenario = scenario
        self._heap: list[_Entry] = []
        self._sequence = count()
        self._best_g: dict[TowerConfiguration, int] = {}

    def __bool__(self) -> bool:
        return bool(self._heap)

    def offer(
        self, state: TowerConfiguration, g: int, action: PlacementAction | None
    ) -> bool:
        previous = self._best_g.get(state)
        if previous is not None and g >= previous:
            return False
        self._best_g[state] = g
        f = g + heuristic(state, self._scenario)
        heappush(self._heap, (f, next(self._sequence), g, state, action))
        return True

    def pop(self) -> tuple[int, TowerConfiguration, PlacementAction | None] | None:
        """Remove one entry; None marks a stale entry, never a counted expansion."""
        _, _, g, state, action = heappop(self._heap)
        if g != self._best_g.get(state):
            return None
        return g, state, action


def format_teaching_trace(result: SearchResult, scenario: Scenario) -> str:
    """Render a bounded expansion prefix using the established grid renderer."""
    if result.algorithm is not AlgorithmName.ASTAR:
        raise ValueError("An A* result is required.")
    lines = [
        "2. A* algorithm",
        "Teaching A* traversal on placement depth",
        f"Target depth: {scenario.max_towers}",
        "G = placements so far; h = placements still needed; f = g + h (min-priority).",
        "The h value does not estimate defense quality. Recommendations show the best evaluated outcome only.",
        "S=spawn, B=base, #=path, +=free build site, .=other cell",
        "A=Arrow, C=Cannon, N=Sniper",
        "Path: " + " -> ".join(str(cell) for cell in scenario.path),
    ]
    for stage, step in enumerate(result.trace):
        action = (
            f"{step.action.tower_type_id.value}@{step.action.cell_id}"
            if step.action
            else "Initial configuration"
        )
        goal = is_target_depth(step.configuration, scenario)
        lines.extend(
            [
                "",
                f"Stage {stage}",
                f"Depth {step.depth}; action: {action}",
                f"g={step.g}, h={step.h}, f={step.f}; target-depth goal: {goal}",
                render_configuration(step.configuration, scenario),
                f"Defeated: {step.outcome[0]}; base health: {step.outcome[1]}",
            ]
        )
    if not result.trace:
        lines.append(
            "No retained expansion stages (trace disabled or no states expanded)."
        )
    if result.trace_steps_dropped:
        lines.append(
            f"Trace truncated: {result.trace_steps_dropped} expansion stages omitted."
        )
    lines.append(
        f"Termination: {result.termination_reason.value}; "
        f"states explored: {result.states_explored}"
    )
    return "\n".join(lines)


def astar(
    scenario: Scenario = DEFAULT_SCENARIO, limits: SearchLimits = SearchLimits()
) -> SearchResult:
    """Evaluate all non-stale unique popped states until exhaustion or a limit.

    Follow shared measurement/counting boundaries, including initial fallback
    evaluation even with zero limits. Shallow and unreachable-depth candidates
    remain eligible for the gameplay best. Time checks are cooperative; completed
    simulations can improve best-so-far before the next deadline check. A full
    frontier/known-g table can consume substantial memory despite bounded traces.
    """
    with RunInstrumentation() as metrics:
        evaluator = SearchEvaluator(scenario)
        tracker = ExpansionTracker(limits)
        trace = TraceBuffer(limits.max_trace_steps)
        initial = TowerConfiguration()
        initial_outcome = evaluator.evaluate(initial)
        frontier = _Frontier(scenario)
        frontier.offer(initial, 0, None)
        reason = TerminationReason.EXHAUSTED
        try:
            while frontier:
                check_time_limit(limits, metrics.elapsed_seconds)
                entry = frontier.pop()
                if entry is None:
                    continue
                g, state, action = entry
                if not tracker.admit(state, metrics.elapsed_seconds):
                    continue
                outcome = initial_outcome if g == 0 else evaluator.evaluate(state)
                h = heuristic(state, scenario)
                trace.append(
                    evaluator.trace_step(state, action, g, outcome, g=g, h=h, f=g + h)
                )
                # Target-depth states have no successors under the shared tower
                # limit. They are evaluated/traced, not used as a stopping rule.
                check_time_limit(limits, metrics.elapsed_seconds)
                for next_action in legal_actions(state, scenario):
                    check_time_limit(limits, metrics.elapsed_seconds)
                    successor = apply_action(state, next_action, scenario)
                    frontier.offer(successor, g + 1, next_action)
        except SearchLimitReached as stopped:
            reason = stopped.reason

    assert (
        evaluator.best_configuration is not None and evaluator.best_outcome is not None
    )
    return SearchResult(
        algorithm=AlgorithmName.ASTAR,
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
