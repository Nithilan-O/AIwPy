"""Small orchestration and presentation layer over shared search contracts."""

from .astar import astar, format_teaching_trace as astar_trace
from .bfs import bfs, format_teaching_trace as bfs_trace
from .config import DEFAULT_SCENARIO
from .domain import Scenario
from .hill_climbing import hill_climbing, format_teaching_trace as hill_trace
from .search_common import AlgorithmName, SearchLimits, SearchResult


# Insertion order is also classroom/report order. No search logic belongs here.
_ALGORITHMS = {
    "bfs": (AlgorithmName.BFS, "1. BFS", bfs, bfs_trace),
    "astar": (AlgorithmName.ASTAR, "2. A* algorithm", astar, astar_trace),
    "hill-climbing": (
        AlgorithmName.HILL_CLIMBING,
        "3. Simple hill climbing",
        hill_climbing,
        hill_trace,
    ),
}
ALGORITHM_CHOICES = (*_ALGORITHMS, "all")

_BEHAVIOR = {
    AlgorithmName.BFS: (
        "BFS expands by placement depth with a FIFO queue. It continues after a "
        "perfect defense; limited runs recommend the best evaluated state only."
    ),
    AlgorithmName.ASTAR: (
        "Teaching A* uses g=placements, h=max_towers-g, and f=g+h. Every legal "
        "state has the same f score, so stable ties produce a BFS-like order. "
        "The heuristic does not estimate defense quality; limited runs recommend "
        "the best evaluated state only."
    ),
    AlgorithmName.HILL_CLIMBING: (
        "Simple hill climbing evaluates every legal one-placement neighbor and "
        "moves to the best only on strict improvement. Equal/worse moves are "
        "rejected. It can stop at a local optimum or plateau; no global optimum "
        "is implied. Interrupted neighbor scans retain the current accepted state."
    ),
}


def run_searches(
    selection: str = "all",
    scenario: Scenario = DEFAULT_SCENARIO,
    limits: SearchLimits = SearchLimits(),
) -> tuple[SearchResult, ...]:
    """Run one or all algorithms with the exact same immutable inputs.

    Each run owns its usual fresh instrumentation context and full allowance;
    limits are per algorithm, never a shared diminishing pool. Return existing
    SearchResult objects without recomputing outcomes or comparing spending.
    """
    if selection not in ALGORITHM_CHOICES:
        raise ValueError(
            f"Unknown algorithm {selection!r}; choose " + ", ".join(ALGORITHM_CHOICES)
        )
    selected = _ALGORITHMS.values() if selection == "all" else (_ALGORITHMS[selection],)
    return tuple(search(scenario, limits) for _, _, search, _ in selected)


def format_trace(result: SearchResult, scenario: Scenario) -> str:
    """Public adapter for the existing algorithm-specific teaching formatters."""
    formatter = next(
        spec[3] for spec in _ALGORITHMS.values() if spec[0] is result.algorithm
    )
    return formatter(result, scenario)


def _format_result(result: SearchResult, scenario: Scenario, trace: bool) -> str:
    """Present the original simulator outcome and measurements without ranking."""
    _, heading, _, _ = next(
        spec for spec in _ALGORITHMS.values() if spec[0] is result.algorithm
    )
    lines = [heading, _BEHAVIOR[result.algorithm], "Recommended towers (row, column):"]
    if not result.best_configuration.placements:
        lines.append("  (empty configuration; no towers)")
    for placement in result.best_configuration.placements:
        tower = scenario.tower(placement.tower_id)
        lines.append(f"  {tower.name} [{tower.id.value}] at {placement.cell}")
    outcome = result.simulation_result
    lines.extend(
        [
            f"Outcome: defeated={outcome.enemies_defeated}, escaped={outcome.enemies_escaped}, "
            f"remaining base health={outcome.base_health_remaining}",
            f"Runtime: {result.elapsed_seconds:.6f} s",
            f"Explored states: {result.states_explored}",
            f"Peak memory: {result.peak_memory_bytes} bytes (traced Python allocations)",
            f"Termination: {result.termination_reason.value}",
        ]
    )
    if trace:
        # Existing formatters supply the numbered heading already shown above.
        lines.extend(
            ["Teaching trace:", format_trace(result, scenario).partition("\n")[2]]
        )
    return "\n".join(lines)


def format_report(
    results: tuple[SearchResult, ...],
    scenario: Scenario,
    limits: SearchLimits,
    *,
    trace: bool = False,
) -> str:
    """Format outside search measurement; never simulate or change a result."""
    lines = [
        "Intelligent tower defense optimizer",
        f"Scenario: {scenario.rows}x{scenario.columns}; enemies={scenario.enemy_count}; "
        f"initial base health={scenario.base_health}; budget={scenario.budget}; "
        f"max towers={scenario.max_towers}",
        f"Per-algorithm limits: max expanded states={limits.max_expanded_states}; "
        f"time limit seconds={limits.time_limit_seconds}; trace steps={limits.max_trace_steps}",
        "Objective: maximize (enemies defeated, remaining base health) lexicographically: "
        "more defeats first, then more health. Coins spent and runtime/memory never rank outcomes.",
        "Explored = unique states admitted for expansion, including initial/terminal states; "
        "generated/evaluated-only neighbors do not count.",
        "All searches start empty and use the same simulator. Limits apply separately to each run.",
        "Time limits are cooperative; one simulation may overrun. Peak memory is not process RSS.",
        "Runtime/memory vary between runs; time-limited recommendations may also vary.",
        "See README.md for scenario, contracts, and teaching details.",
    ]
    lines.extend("\n" + _format_result(result, scenario, trace) for result in results)
    return "\n".join(lines)
