# Intelligent Tower Defense Optimizer

An educational Python application demonstrating BFS, A* Search, and Simple Hill
Climbing choosing tower types and placements on a grid for one deterministic
tower-defense wave. Each algorithm uses the same fixed scenario
and shared game contracts so its choices can be explained state by state.

The project provides an installable package, an argparse CLI, a small application
service, immutable domain types, a validated fixed scenario, and a deterministic
simulator with a shared gameplay objective. BFS, teaching A*, and Simple Hill
Climbing are implemented. A graphical UI and benchmarks remain deferred.

## Fixed scenario

`config.py` is the single source of truth for `DEFAULT_SCENARIO`. Coordinates are
zero-based `(row, column)` pairs on a 10x10 grid. The ordered 15-cell path runs
from spawn `(2, 0)` across row 2 through `(2, 7)`, down column 7 to `(7, 7)`,
then across row 7 to the base at `(7, 9)`. Eight buildable cells sit off the path:
`(1, 2)`, `(1, 6)`, `(3, 4)`, `(4, 6)`, `(4, 8)`, `(6, 6)`, `(6, 8)`, `(8, 9)`.
The limited sites near straights and bends offer different coverage choices.

One wave contains 20 enemies, each with 100 health and speed 1 path cell/second.
The base starts with 10 health; each enemy reaching it deals 1 damage. The build
budget is 500 credits with at most 4 towers. Timing defaults are a 0.1-second
tick, 1-second spawn interval, and 60-second wave limit.

| Tower ID | Name | Cost (credits) | Range (cells) | Damage | Cooldown (seconds) |
| --- | --- | --- | --- | --- | --- |
| `arrow` | Arrow | 100 | 2.5 | 12 | 0.5 |
| `cannon` | Cannon | 175 | 2.0 | 30 | 1.5 |
| `sniper` | Sniper | 225 | 4.0 | 45 | 2.0 |

These fixed values provide affordable short-range towers and more expensive
alternatives with different ranges and firing rates. They are demonstration
values; no balance tuning or performance benchmarking has been performed.

`domain.py` uses frozen values and `TowerId` enums. Tower configurations sort
placements canonically, so insertion order does not affect equality or hashing.
`Scenario.validate_state()` checks build sites, total cost, and the tower limit;
placement construction checks IDs and coordinates without assuming a scenario.

## Placement contract

`actions.py` defines frozen `PlacementAction(cell_id, tower_type_id)` values using
the existing `(row, column)` coordinates and `TowerId` enum. `legal_actions(state,
scenario)` is the sole placement-legality generator, returning a tuple ordered by
row, column, then tower ID string. It enforces build sites, occupancy, known tower
types, budget, and tower count. `apply_action` accepts only generated legal actions
and returns a new canonical configuration without mutating its input. Invalid
actions or source configurations raise `ValueError`.

`can_stop` is true for every valid configuration, including the empty one and all
intermediate depths. Stopping selects the current configuration as final; there
is no stop action or self-loop. `is_terminal` means no further tower placement is
legal, whether due to budget, tower count, or occupied sites. `budget_used` reports
spending solely for legality and explanation, never performance scoring or
tie-breaking. Action ordering does not depend on cost.

## Simulation and evaluation contract

`simulate(configuration, scenario)` in `simulator.py` validates the configuration
and runs one wave using only local mutable working data. The default wave has
20 identical enemies. It returns a frozen `SimulationResult` with defeated and
escaped counts, remaining base health, and a tuple of frozen `SimulationEvent`
records for future playback. All enemies finish as defeated or escaped, including
after base health reaches zero. Base health is clamped to `[0, initial health]`.

Time is indexed by integer ticks, starting at tick 0. Enemy IDs start at 0 and
increase with spawn order. Enemy `i` spawns at the first tick at or after
`i * spawn_interval_seconds`. Each tick follows this order:

1. Spawn due enemies at path progress 0, in enemy ID order.
2. Move previously spawned enemies by speed times tick duration, in enemy ID
   order. Position is linearly interpolated along the ordered path segments;
   progress is clamped to the final cell. New spawns do not move on their spawn tick.
3. Resolve escapes at the final path cell in enemy ID order, applying leak damage.
   An enemy arriving at the base cannot be shot on that tick.
4. Fire ready towers in canonical placement order. Target the living in-range
   enemy with greatest path progress, then the lowest enemy ID. Range is inclusive
   Euclidean distance between grid coordinates. Shots deal immediate single-target
   damage without splash; kills are removed before the next tower fires.

Towers start ready at tick 0, fire at most once per tick, and become ready again
after `ceil(cooldown / tick_duration)` ticks. A tower with no target stays ready.
Towers never block movement. Decimal configuration numbers are converted to exact
rationals internally to avoid accumulated floating-point timing drift; trace
positions and progress are exported as floats. Events record spawn, movement,
shot, defeat, and escape, with ticks, enemy status, base health, and firing tower
identity where applicable. Identical inputs produce identical event sequences.

The wave limit must cover the last quantized spawn plus the entire path travel
time rounded up to ticks. A shorter limit raises `ValueError` before simulation;
unfinished or unspawned enemies are never counted as escaped. A run ends early
only when every enemy has been resolved.

`evaluation.py` exposes `objective_key(result)` as
`(enemies_defeated, base_health_remaining)`, maximized lexicographically, and
`compare_outcomes(left, right)` returning 1, 0, or -1 for better, tied, or worse.
Escapes are reported and equal wave size minus defeats. Spending, event count,
simulation duration, and future search/runtime metrics do not break objective ties.

## Shared search bookkeeping

`search_common.py` supplies one frozen `SearchResult` for the three named
algorithms: best configuration and its simulation outcome, elapsed seconds,
`states_explored`, peak traced bytes, typed termination reason, and optional trace.
All three algorithms use these contracts.

`ExpansionTracker.admit` counts each unique canonical state when it is removed
for expansion, before inspecting goal or terminal status. Initial, goal, and
terminal states count; generated/evaluated-only states and duplicate removals do
not. A `False` return means a duplicate. The cap is checked before admitting the
next unique state, so the count never exceeds it. Exhausting the frontier or
finding a goal on the last permitted expansion can still finish normally.

`SearchEvaluator` calls the existing simulator and retains the first encountered
configuration on objective ties. Only `(defeated, remaining_base_health)` selects
the best; cost and instrumentation never break ties. It does not count expansions
or cache outcomes. Future algorithms must evaluate the initial configuration as
a fallback, then check limits before expansions and subsequent evaluations.

`SearchLimits` defaults to 10,000 unique expansions, no time limit, and 100 trace
steps. Zero expansions/time is supported. `check_time_limit` and the expansion
tracker raise `SearchLimitReached` with `TIME_LIMIT` or `MAX_EXPANDED_STATES`;
future algorithms must catch it and return the best-so-far result with that reason.
At a check, elapsed time equal to the deadline is expired and takes precedence
over the expansion cap. Time checks are cooperative: a simulator call or initial
fallback evaluation can overrun the deadline. Normal reasons are exhausted search
space, goal reached, or no improving neighbor; each algorithm must select the
appropriate reason rather than claim success when a resource limit stops it.

`TraceStep` stores configuration, incoming placement action (`None` initially),
depth, compact objective outcome, and optional numeric `g/h/f`. These fields do
not redefine the gameplay objective. `TraceBuffer` retains the first configured
number of steps in order and counts dropped entries; zero disables recording.
Use `SearchLimits.max_trace_steps` for both buffer capacity and
`SearchResult.trace_limit`, and copy the dropped count into the result. Results
reject traces exceeding their declared cap. Search traces omit simulator event
logs; the best outcome retains its playback data.

Use a fresh `RunInstrumentation` context around initialization/fallback evaluation,
search work, simulation calls, and trace collection. Read final metrics and
construct `SearchResult` after exiting; imports, scenario creation, and result
formatting are outside the measurement. Elapsed time uses `perf_counter` wall
time. Memory is the peak Python allocation count from a fresh `tracemalloc`
session, including bookkeeping overhead; it is not process RSS or native memory.
Tracing adds overhead and unrelated threads' allocations can affect the peak.

Instrumentation owns and resets only its newly started tracer, then stops it on
normal or exceptional exit. It rejects overlapping helper sessions and existing
external tracing without resetting/stopping them. Do not start/stop/reset an
external tracer during the context. Contexts are single-use; sequential runs each
start fresh. Runtime and memory measurements are observational and may vary even
when gameplay outcomes and traces are deterministic.

## Setup

Requires Python 3.10 or newer. Run commands from this repository directory.
There are no runtime or test dependencies outside the Python standard library.
Setuptools is the packaging build dependency declared in `pyproject.toml`.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
```

On macOS/Linux, use `.venv/bin/python` in place of
`.venv\Scripts\python.exe` in these commands.

## Run

From the repository on macOS/Linux, run without installing by setting
`PYTHONPATH=src`. No arguments or `--help` prints usage without starting a search.

```sh
PYTHONPATH=src python3 -m tower_defense_optimizer --help
PYTHONPATH=src python3 -m tower_defense_optimizer --algorithm bfs --max-expanded-states 4
PYTHONPATH=src python3 -m tower_defense_optimizer --algorithm astar --max-expanded-states 4 --trace --trace-steps 2
PYTHONPATH=src python3 -m tower_defense_optimizer --algorithm hill-climbing --trace --trace-steps 4
PYTHONPATH=src python3 -m tower_defense_optimizer --algorithm all --max-expanded-states 4 --trace --trace-steps 2
PYTHONPATH=src python3 -m tower_defense_optimizer --algorithm all --budget 300 --max-towers 2 --time-limit 1 --trace --trace-steps 1
```

After installing with the setup commands, use `.venv/bin/python -m tower_defense_optimizer`
(on Windows `.venv\Scripts\python.exe -m tower_defense_optimizer`)
or the installed `tower-defense-optimizer` command with
the same options. For example:

```powershell
.venv\Scripts\python.exe -m tower_defense_optimizer --algorithm all --max-expanded-states 4
```

`--algorithm` accepts `bfs`, `astar`, `hill-climbing`, or `all`. All mode runs in
numbered classroom order, sequentially, using the exact same immutable scenario
and `SearchLimits` for each run. The expansion/time allowances reset for each
algorithm. `--budget` and `--max-towers` override only those default scenario
settings for every selected algorithm; coordinates remain zero-based `(row,
column)`. Budget must be nonnegative and max towers must be at least one.

`--max-expanded-states` defaults to 10000; `--time-limit` defaults to no deadline.
Both accept zero, returning the simulator-evaluated empty fallback without
expansion. Time must be finite and nonnegative. Checks are cooperative: a single
simulation may overrun the deadline. A large expansion allowance can take time,
especially with the default wave; use a small cap for classroom demonstrations.

`--trace` enables teaching output. `--trace-steps N` caps the retained/output
stages **per algorithm**, defaults to 5, and accepts zero. It does not limit the
search itself. Without `--trace`, no stages are retained or printed. Traces show
only the retained prefix and explicitly report omitted stages. BFS/A* stages are
expansion order; hill-climbing stages are the accepted path and include the best
neighbor comparison. A* stages include g/h/f. A final recommendation may be
outside a truncated trace.

Reports show each recommended tower type and cell, the original shared simulator
outcome (defeated, escaped, remaining base health), elapsed seconds, explored
states, peak traced Python bytes, and the typed termination reason. Formatting is
stable; runtime and memory are observations that vary between runs. Time-limited
recommendations can also vary. All algorithms maximize defeats first, then base
health; coins spent and runtime/memory do not break gameplay ties. Results are
reported independently without assigning an overall winner.

Illustrative excerpt only, **not measured output** (metric values below are
invented to demonstrate formatting; other sections and trace rows are omitted):

```text
3. Simple Hill Climbing
Simple Hill Climbing evaluates every legal one-placement neighbor and moves to the best only on strict improvement. Equal/worse moves are rejected. It can stop at a local optimum or plateau; no global optimum is implied. Interrupted neighbor scans retain the current accepted state.
Recommended towers (row, column):
  Arrow [arrow] at (1, 6)
  Sniper [sniper] at (3, 4)
  Arrow [arrow] at (4, 6)
Outcome: defeated=9, escaped=11, remaining base health=0
Runtime: 1.234567 s
Explored states: 4
Peak memory: 3000000 bytes (traced Python allocations)
Termination: no_improving_neighbor
```

## Application service

`application.py` keeps orchestration separate from search: `run_searches` invokes
existing algorithms, `_format_result` formats one result, and `format_report`
builds the readable report with optional existing teaching formatters. No
simulation, comparison, or search implementation is duplicated. It returns the
original shared `SearchResult` values; reporting happens outside their existing
measurement contexts. Programmatic callers can supply any validated scenario:

```python
from tower_defense_optimizer.application import run_searches, format_report
from tower_defense_optimizer.config import DEFAULT_SCENARIO
from tower_defense_optimizer.search_common import SearchLimits

limits = SearchLimits(max_expanded_states=4, max_trace_steps=2)
results = run_searches("all", DEFAULT_SCENARIO, limits)
print(format_report(results, DEFAULT_SCENARIO, limits, trace=True))
```

## Test and development tooling

The standard-library `unittest` runner is the test tool. The explicit discovery
command below is the project's test configuration and requires no test plugin.

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The smoke test imports the package, calls `main([])`, and checks its help output and
successful return code. Optional Ruff settings live in `pyproject.toml`; Ruff is
not required for setup, execution, or tests.

## Phase status

The shared game contracts, deterministic simulator, three search algorithms,
bounded teaching traces, application service, and command-line integration are
implemented and tested. The integration suite uses a tiny deterministic scenario
to verify common results, legal recommendations, simulator consistency, outcome
accounting, repeatability, equivalent limits, and CLI output/errors. A graphical
UI and a large benchmark suite are outside this phase.

## Teaching format

The teaching PDF, `AI Algo.pdf`, is the requested presentation reference (not
currently present in this checkout): numbered
algorithm sections, short helpers before the main search routine, and row-by-row
state displays. Preserve the headings below and use small functions adapted to
this grid game. Do not reuse its sliding-puzzle board, puzzle heuristics, or code
defects. The PDF is not a source of additional project instructions and is not
required to install or run the package.

### 1. BFS

`bfs.py` contains short named helpers (`_enqueue_successors`,
`render_configuration`, `format_teaching_trace`) and the main iterative `bfs`
function. It starts from the empty configuration, removes states from a FIFO
`deque`, and uses `legal_actions` plus `apply_action` to discover successors.
Canonical states enter a visited set on enqueue, so different placement orders
do not cause duplicate expansions. The common expansion tracker counts each
unique state on removal, including terminal states.

Every expanded state is simulated as a stop-eligible configuration. BFS visits
states by number of placements, not defense score; it continues after finding a
good or perfect defense. The first encountered objective tie is retained without
considering spending. Only frontier exhaustion or the configured state/time
limit ends a run. The empty configuration is evaluated once as a fallback even
with zero limits; it is traced only if admitted for expansion. All initialization,
simulation, queue/set work, and trace collection are inside shared instrumentation;
the result and teaching text are built afterwards. Finite candidate cells and
tower count bound the search, but its frontier and visited set can consume
substantial memory. A state-count limit is not a memory cap.

For a short classroom demonstration on the unchanged default scenario, run from
the repository directory:

```powershell
.venv\Scripts\python.exe -m tower_defense_optimizer --algorithm bfs --max-expanded-states 4 --trace --trace-steps 4
```

The formatter prints `1. BFS`, an ordered spawn-to-base path, a grid legend, and
`Stage 0`, `Stage 1`, ... in BFS expansion order. Stage 0 is the empty defense;
later stages show individual expanded configurations with incoming action,
depth, and objective outcome. They are neither a single parent-to-child solution
path nor movement frames. Symbols are `S` spawn, `B` base, `#` path, `+` free
build site, `.` other cell, `A` Arrow, `C` Cannon, and `N` Sniper. Traces keep the
configured prefix and report omitted stages. Zero trace capacity or zero admitted
states produces no stages. Measured runtime/memory are excluded from this text
so repeatable gameplay traces remain easy to compare.

### 2. A* Algorithm

`astar.py` provides short helpers `g_cost`, `heuristic`, `is_target_depth`, a heap
frontier helper, and the main `astar` function. This is a **teaching A* traversal
on placement depth** over the same configuration graph as BFS:

- `g` counts placements already made: every placement costs one search step.
- The fixed target depth is `scenario.max_towers`. `h = max(0, target_depth - g)`
  counts placements still needed. When a legal completion exists, this is the
  exact minimum additional number of steps to reach that depth.
- `f = g + h` is the min-priority traversal key. It does not measure defense quality.

A fixed-depth goal is a valid configuration containing exactly `max_towers`
towers. Insufficient remaining sites or credits may make the goal unreachable;
the finite depth gap is then only a lower bound, not a promise of completion.
Those shallow dead ends remain eligible for gameplay evaluation. No reachability
pruning removes them. In this graph every legal state has `f = target_depth`, so
the stable insertion sequence produces the same expansion order as BFS. This is
an intentionally simple illustration of the `g+h` pattern, not a defense heuristic.

The frontier is a min-heap retaining multiple equal-priority entries with unique
sequence numbers, not a dictionary keyed by `f`. Best-known `g` is stored by
canonical configuration; equal/worse rediscoveries are ignored, and stale popped
entries are skipped before evaluation/counting/tracing. Strict improvements are
supported by the bookkeeping, although all real routes to a configuration here
have identical unit cost. Unlike the teaching PDF's frontier, equal `f` does not
overwrite states, and the frontier is retained across expansions.

Every unique non-stale popped state is evaluated, including the empty defense,
stop-eligible shallow states, unreachable-depth dead ends, and target-depth goals.
The search continues after a depth goal or perfect defense until exhaustion or a
resource limit. The recommendation uses only the shared
`(enemies_defeated, base_health_remaining)` objective, preserving the first tie.
With limits it is best among evaluated configurations only: do not interpret the
first depth goal, smallest `f`, or returned limited result as the best defense or
an optimal gameplay configuration. Shared fallback, counting, cooperative time
checks, bounded traces, and instrumentation boundaries are unchanged.

```powershell
.venv\Scripts\python.exe -m tower_defense_optimizer --algorithm astar --max-expanded-states 4 --trace --trace-steps 4
```

The teaching formatter uses `2. A* Algorithm`, then `Stage 0`, `Stage 1`, ... in
expansion order. Each stage shows the fixed path/grid, tower symbols from the BFS
legend, incoming action, objective outcome, `g`, `h`, `f`, and whether it is a
target-depth goal. Stage 0 is the initial empty configuration if admitted. Trace
limits and zero-budget resource allowances behave as documented for BFS; the
formatter reports missing/truncated stages rather than inventing expansions.

### 3. Simple Hill Climbing

`hill_climbing.py` organizes the explanation into `_tie_key`, `_prefer`,
`format_teaching_trace`, and the main iterative `hill_climbing` function.
The deterministic initial configuration is empty. Each iteration generates all
legal one-placement neighbors through `legal_actions`, constructs them with
`apply_action`, and evaluates them through the shared simulator/evaluator.
It selects the maximum shared `(defeated, remaining_base_health)` objective;
objective ties choose the smallest canonical placement tuple (cell, tower ID),
then action (cell, tower ID), independent of generation order and spending.
Only strict gameplay improvement permits a move. Equal and worse neighbors are
rejected. There are no sideways moves, restarts, removals, or recursive calls.

No improving neighbor (including no legal actions) returns `LOCAL_OPTIMUM`:
this is a local optimum under one-placement moves, not a global optimum.
Resource limits return the current accepted state with their explicit reason.
A partial neighborhood scan never authorizes a move, even if an evaluated
neighbor improved the objective. The empty fallback is simulated even with zero
limits. Time checks are cooperative before/after neighborhood work and before
each simulation; a single simulation can overrun the deadline.

Explored uses `ExpansionTracker`: count unique current states admitted for
expansion, including initial and terminal states, but exclude evaluated-only
neighbors. An accepted move awaiting admission is returned if the next admission
hits the expansion cap; it is not counted as explored. Reaching a local optimum
on the last allowed expansion still terminates normally. Initialization,
simulations, comparisons, counting, and trace collection are measured inside
`RunInstrumentation`; result construction and formatting are outside, as for BFS/A*.

`HillClimbingStep` extends the shared `TraceStep` contract with a compact best
neighbor configuration/action/objective, evaluated neighbor count, scan-complete
flag, and decision. No per-neighbor list or simulator logs are retained.
`SearchResult` and BFS/A* contracts and behavior remain unchanged.
`Stage 0` is the admitted empty state; each subsequent stage is an accepted move,
including one awaiting admission when a limit stops search. Each stage shows the
current grid/outcome, best evaluated neighbor grid/outcome, and acceptance or stop
reason. An interrupted scan is marked incomplete. Zero initial allowance yields
no stages. Trace capacity retains only the configured prefix and counts omitted
accepted-state stages; disabling/truncating the trace does not affect search.

```powershell
.venv\Scripts\python.exe -m tower_defense_optimizer --algorithm hill-climbing --trace --trace-steps 4
```
