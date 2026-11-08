"""Shared search contracts and bookkeeping, without search implementations."""

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from threading import Lock
from time import perf_counter
import tracemalloc

from . import simulator
from .actions import PlacementAction
from .domain import Scenario, TowerConfiguration
from .evaluation import compare_outcomes, objective_key
from .simulator import SimulationResult


DEFAULT_TRACE_LIMIT = 100


class AlgorithmName(str, Enum):
    BFS = "BFS"
    ASTAR = "A* algorithm"
    HILL_CLIMBING = "Simple hill climbing"


class TerminationReason(str, Enum):
    EXHAUSTED = "search_space_exhausted"
    GOAL_REACHED = "goal_reached"
    LOCAL_OPTIMUM = "no_improving_neighbor"
    MAX_EXPANDED_STATES = "max_expanded_states"
    TIME_LIMIT = "time_limit"


def _nonnegative_int(name: str, value: int) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(
            f"{name.replace('_', ' ').capitalize()} must be a nonnegative integer."
        )


def _finite_nonnegative(name: str, value: float) -> None:
    if type(value) not in (int, float) or not isfinite(value) or value < 0:
        raise ValueError(
            f"{name.replace('_', ' ').capitalize()} must be a finite nonnegative number."
        )


@dataclass(frozen=True, slots=True)
class SearchLimits:
    max_expanded_states: int = 10_000
    time_limit_seconds: float | None = None
    max_trace_steps: int = DEFAULT_TRACE_LIMIT

    def __post_init__(self) -> None:
        _nonnegative_int("max_expanded_states", self.max_expanded_states)
        _nonnegative_int("max_trace_steps", self.max_trace_steps)
        if self.time_limit_seconds is not None:
            _finite_nonnegative("time_limit_seconds", self.time_limit_seconds)


@dataclass(frozen=True, slots=True)
class TraceStep:
    configuration: TowerConfiguration
    action: PlacementAction | None
    depth: int
    outcome: tuple[int, int]  # objective_key, without the simulator event log
    g: float | None = None
    h: float | None = None
    f: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.configuration, TowerConfiguration):
            raise ValueError("Configuration must be a TowerConfiguration.")
        if self.action is not None and not isinstance(self.action, PlacementAction):
            raise ValueError("Action must be a PlacementAction or None.")
        _nonnegative_int("depth", self.depth)
        outcome = tuple(self.outcome)
        if len(outcome) != 2:
            raise ValueError(
                "Outcome must contain defeated count and remaining health."
            )
        for value in outcome:
            _nonnegative_int("outcome value", value)
        object.__setattr__(self, "outcome", outcome)
        for name in ("g", "h", "f"):
            value = getattr(self, name)
            if value is not None:
                _finite_nonnegative(name, value)


class TraceBuffer:
    """Retain the first N steps in order; count dropped steps without storing them."""

    def __init__(self, max_steps: int = DEFAULT_TRACE_LIMIT) -> None:
        _nonnegative_int("max_steps", max_steps)
        self._max_steps = max_steps
        self._steps: list[TraceStep] = []
        self._dropped = 0

    def append(self, step: TraceStep) -> None:
        if not isinstance(step, TraceStep):
            raise ValueError("Step must be a TraceStep.")
        if len(self._steps) < self._max_steps:
            self._steps.append(step)
        else:
            self._dropped += 1

    @property
    def steps(self) -> tuple[TraceStep, ...]:
        return tuple(self._steps)

    @property
    def dropped_steps(self) -> int:
        return self._dropped


@dataclass(frozen=True, slots=True)
class SearchResult:
    algorithm: AlgorithmName
    best_configuration: TowerConfiguration
    simulation_result: SimulationResult
    elapsed_seconds: float
    states_explored: int
    peak_memory_bytes: int
    termination_reason: TerminationReason
    trace: tuple[TraceStep, ...] = ()
    trace_limit: int = DEFAULT_TRACE_LIMIT
    trace_steps_dropped: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.algorithm, AlgorithmName):
            raise ValueError("Algorithm must be an AlgorithmName.")
        if not isinstance(self.best_configuration, TowerConfiguration):
            raise ValueError("Best configuration must be a TowerConfiguration.")
        if not isinstance(self.simulation_result, SimulationResult):
            raise ValueError("Simulation result must be a SimulationResult.")
        if not isinstance(self.termination_reason, TerminationReason):
            raise ValueError("Termination reason must be a TerminationReason.")
        _finite_nonnegative("elapsed_seconds", self.elapsed_seconds)
        for name in (
            "states_explored",
            "peak_memory_bytes",
            "trace_limit",
            "trace_steps_dropped",
        ):
            _nonnegative_int(name, getattr(self, name))
        trace = tuple(self.trace)
        if len(trace) > self.trace_limit:
            raise ValueError("Trace exceeds its limit.")
        if any(not isinstance(step, TraceStep) for step in trace):
            raise ValueError("Trace must contain TraceStep values.")
        object.__setattr__(self, "trace", trace)


class SearchLimitReached(RuntimeError):
    def __init__(self, reason: TerminationReason) -> None:
        if not isinstance(reason, TerminationReason) or reason not in (
            TerminationReason.MAX_EXPANDED_STATES,
            TerminationReason.TIME_LIMIT,
        ):
            raise ValueError("Reason must describe a resource limit.")
        self.reason = reason
        super().__init__(reason.value)


def check_time_limit(limits: SearchLimits, elapsed_seconds: float) -> None:
    """Cooperative check; one in-progress operation may overrun the deadline."""
    _finite_nonnegative("elapsed_seconds", elapsed_seconds)
    if (
        limits.time_limit_seconds is not None
        and elapsed_seconds >= limits.time_limit_seconds
    ):
        raise SearchLimitReached(TerminationReason.TIME_LIMIT)


class ExpansionTracker:
    """Count a unique state on removal/admission for expansion, before goal checks.

    Goal and terminal states count even though they generate no successors.
    Generated/evaluated-only states and duplicate removals do not count. Call
    admit() for the initial state too; False means a duplicate, not termination.
    Catch SearchLimitReached and use its reason in the final SearchResult.
    """

    def __init__(self, limits: SearchLimits) -> None:
        self.limits = limits
        self._expanded: set[TowerConfiguration] = set()

    @property
    def states_explored(self) -> int:
        return len(self._expanded)

    def admit(self, state: TowerConfiguration, elapsed_seconds: float) -> bool:
        if not isinstance(state, TowerConfiguration):
            raise ValueError("State must be a TowerConfiguration.")
        check_time_limit(self.limits, elapsed_seconds)
        if state in self._expanded:
            return False
        if self.states_explored >= self.limits.max_expanded_states:
            raise SearchLimitReached(TerminationReason.MAX_EXPANDED_STATES)
        self._expanded.add(state)
        return True


class SearchEvaluator:
    """Evaluate via the one simulator; strictly better outcomes replace the best.

    Objective ties preserve the first encountered configuration. No caching or
    exploration counting occurs here. Evaluate the initial configuration as a
    fallback, even with a zero expansion/time allowance.
    """

    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario
        self.best_configuration: TowerConfiguration | None = None
        self.best_outcome: SimulationResult | None = None

    def evaluate(self, state: TowerConfiguration) -> SimulationResult:
        outcome = simulator.simulate(state, self.scenario)
        if (
            self.best_outcome is None
            or compare_outcomes(outcome, self.best_outcome) > 0
        ):
            self.best_configuration = state
            self.best_outcome = outcome
        return outcome

    def trace_step(
        self,
        state: TowerConfiguration,
        action: PlacementAction | None,
        depth: int,
        outcome: SimulationResult,
        **scores: float,
    ) -> TraceStep:
        return TraceStep(state, action, depth, objective_key(outcome), **scores)


_measurement_lock = Lock()


class RunInstrumentation:
    """Single-use context owning a fresh process-wide tracemalloc session.

    Reject active/external tracers and overlapping sessions without touching them.
    Measure only work inside the context (including simulations and traces).
    Construct SearchResult after exit. Python allocations are not process RSS;
    unrelated threads allocating during this context can affect the peak.
    """

    def __init__(self) -> None:
        self._start: float | None = None
        self._running = False
        self._elapsed = 0.0
        self.peak_memory_bytes = 0

    @property
    def elapsed_seconds(self) -> float:
        if self._running:
            return perf_counter() - self._start
        return self._elapsed

    def __enter__(self) -> "RunInstrumentation":
        if self._start is not None:
            raise RuntimeError("Instrumentation contexts are single-use.")
        if not _measurement_lock.acquire(blocking=False):
            raise RuntimeError("Another search measurement is active.")
        started = False
        try:
            if tracemalloc.is_tracing():
                raise RuntimeError("An external tracemalloc session is already active.")
            tracemalloc.start()
            started = True
            tracemalloc.reset_peak()
            self._start = perf_counter()
            self._running = True
        except BaseException:
            if started:
                tracemalloc.stop()
            _measurement_lock.release()
            raise
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        try:
            self._elapsed = perf_counter() - self._start
            self.peak_memory_bytes = tracemalloc.get_traced_memory()[1]
        finally:
            self._running = False
            tracemalloc.stop()
            _measurement_lock.release()
