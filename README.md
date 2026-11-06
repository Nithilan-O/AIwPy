# Intelligent Tower Defense Optimizer

An educational Python application demonstrating BFS, A* Search, and Simple Hill
Climbing choosing tower types and placements on a grid for one deterministic
tower-defense wave. Each algorithm uses the same fixed scenario
and shared game contracts so its choices can be explained state by state.

The project provides an installable package, an argparse CLI, a small application
service, immutable domain types, a validated fixed scenario, and a deterministic
simulator with a shared gameplay objective. BFS, teaching A*, and Simple Hill
Climbing, repeatable benchmark reporting, and an optional Tk desktop interface
are implemented. A large benchmark suite remains deferred.

## Fixed scenario

`config.py` is the single source of truth for `DEFAULT_SCENARIO`. Coordinates are
zero-based `(row, column)` pairs on a 10x10 grid. The ordered 15-cell path runs
from spawn `(2, 0)` across row 2 through `(2, 7)`, down column 7 to `(7, 7)`,
then across row 7 to the base at `(7, 9)`. Eight buildable cells sit off the path:
`(1, 2)`, `(1, 6)`, `(3, 4)`, `(4, 6)`, `(4, 8)`, `(6, 6)`, `(6, 8)`, `(8, 9)`.
The limited sites near straights and bends offer different coverage choices.

The default scope is exactly one map, one fixed path, one enemy type, and one
wave of 20 identical enemies, each with 100 health and speed 1 path cell/second.
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
values; benchmark reports describe these settings rather than establish game
balance. The GUI uses this fixed scenario. CLI budget/tower-limit overrides are
explicit comparison variants; they do not add maps, enemy types, or waves.

`domain.py` uses frozen values and `TowerId` enums. Tower configurations sort
placements canonically, so insertion order does not affect equality or hashing.
`Scenario.validate_state()` checks build sites, total cost, and the tower limit;
placement construction checks IDs and coordinates without assuming a scenario.

## Architecture and data flow

A **state** is a complete tower configuration before the wave, not a moving enemy
position. A **placement action** adds exactly one tower at one legal build site.
The transition creates a new immutable state; it does not alter the previous one.
The simulator evaluates the entire wave for a configuration from the same initial
conditions each time.

```text
CLI / optional Tk UI / benchmark
              |
              v
application.run_searches(selection, one Scenario, one SearchLimits)
              |
              v
BFS / A* / Simple Hill Climbing
  TowerConfiguration -> legal_actions -> apply_action -> new TowerConfiguration
              |
              v
SearchEvaluator -> simulator.simulate -> SimulationResult -> objective_key
              |
              v
SearchResult (configuration + its outcome + metrics + termination + bounded trace)
              |
              v
terminal report / JSON export / UI view model and grid
```

`config.py` supplies defaults; `domain.py` validates immutable domain values;
`actions.py` owns placement legality and transitions. `simulator.py` is the single
wave implementation and `evaluation.py` owns the lexicographic objective.
`search_common.py` owns result/counting/limit/measurement contracts. The three
algorithm modules own traversal decisions only. `application.py` orchestrates
sequential runs with the same inputs and exposes the existing trace formatters.
`benchmark.py` records provenance and operational summaries; `ui_model.py` adapts
shared results for `gui.py`. Front ends do not implement another simulator,
objective, or search algorithm.

For example, start with `TowerConfiguration()` (no towers). The action
`PlacementAction((1, 2), TowerId.ARROW)` legally creates a configuration containing
one Arrow at row 1, column 2. Adding a Cannon at `(1, 6)` creates a second state
with both towers. Each configuration is independently stop-eligible and simulated;
placing another tower is not assumed to improve its score. Reversing these two
placements yields the same canonical state, so BFS/A* avoid expanding it twice.

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
simulation duration, and search/runtime metrics do not break objective ties.

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
finding no improving neighbor on the last permitted expansion can still finish normally.

`SearchEvaluator` calls the existing simulator and retains the first encountered
configuration on objective ties. Only `(defeated, remaining_base_health)` selects
the best; cost and instrumentation never break ties. It does not count expansions
or cache outcomes. Each implemented algorithm evaluates the initial configuration
as a fallback, then checks limits before expansions and subsequent evaluations.

`SearchLimits` defaults to 10,000 unique expansions, no time limit, and 100 trace
steps. Zero expansions/time is supported. `check_time_limit` and the expansion
tracker raise `SearchLimitReached` with `TIME_LIMIT` or `MAX_EXPANDED_STATES`;
the algorithms catch it and return their best-so-far result with that reason.
At a check, elapsed time equal to the deadline is expired and takes precedence
over the expansion cap. Time checks are cooperative: a simulator call or initial
fallback evaluation can overrun the deadline. Normal reasons are exhausted search
space (BFS/A*) or no improving neighbor (hill climbing). The shared enum also
reserves `GOAL_REACHED`, but none of the current searches uses it as a stopping
rule. A resource-limit reason always remains explicit.

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
time. Memory is the peak size in bytes of traced Python allocations from a fresh
`tracemalloc` session, including bookkeeping overhead; it is not process RSS or native memory.
Tracing adds overhead and unrelated threads' allocations can affect the peak.

Instrumentation owns and resets only its newly started tracer, then stops it on
normal or exceptional exit. It rejects overlapping helper sessions and existing
external tracing without resetting/stopping them. Do not start/stop/reset an
external tracer during the context. Contexts are single-use; sequential runs each
start fresh. Runtime and memory measurements are observational and may vary even
when gameplay outcomes and traces are deterministic.

## The six comparison measures

| Measure | Shared result field | Meaning / unit |
| --- | --- | --- |
| Enemies defeated | `simulation_result.enemies_defeated` | Enemies killed during the complete wave. |
| Enemies escaped | `simulation_result.enemies_escaped` | Enemies reaching the base; defeated + escaped = 20 by default. |
| Remaining base health | `simulation_result.base_health_remaining` | Health after the wave, clamped to 0–10 by default. Zero does not stop simulation early. |
| Execution time | `elapsed_seconds` | Wall-clock seconds inside the search measurement context, including simulation and tracing overhead. |
| Explored states | `states_explored` | Unique canonical states admitted for expansion, including initial/terminal states. Generated or evaluated-only neighbors do not count. |
| Memory usage | `peak_memory_bytes` | Peak size of traced Python allocations, in bytes; the UI displays KiB by dividing by 1024. Not RSS or all native/process memory. |

Only the first and third fields rank configurations: maximize defeats, then
remaining health. Escapes are reported for wave accounting. Runtime, explored
count, memory, and credits spent never break gameplay ties. Under the fixed wave,
health is determined by escapes and leak damage, so the secondary objective may
be redundant; the shared contract still includes it. Lower execution time or
memory alone does not establish a better defense. Termination reason and the
recommended configuration must be read alongside all six measures.

Defaults depend on the entry point, without changing the game settings:

| Entry point | Expanded-state cap | Time limit per algorithm | Trace capacity |
| --- | --- | --- | --- |
| Direct search / `SearchLimits()` | 10000 | None | 100 stages |
| Normal CLI run | 10000 | None | 0 without `--trace`; 5 with it |
| CLI benchmark | 10000 | None | Always 0; 1 repeat by default |
| Optional desktop UI | 32 | 3 seconds | 5 stages; configurable from 0 to 20 |

In all mode the allowance resets for each algorithm; it is not divided by three.
A trace cap limits retained explanation, not expansions, runtime, or memory.

## Setup

Requires Python 3.10 or newer. Run commands from this repository directory.
There are no runtime or test dependencies outside the Python standard library.
Setuptools is the packaging build dependency declared in `pyproject.toml`.
The optional desktop UI additionally needs a working Tcl/Tk installation and a
graphical desktop; the CLI and headless tests do not import Tk.

On macOS/Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

On Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
```

Editable installation makes the package and console commands available to that
interpreter. No activation is required when using the explicit interpreter path.
Installation needs setuptools (and may download build dependencies); for a
checkout-only offline run, use the `PYTHONPATH=src` commands below. Use the same
Python/environment for installation, testing, and running.

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

## Optional desktop interface

The UI uses Python's lightweight Tkinter/ttk toolkit, with no additional pip
runtime dependency. It displays the unchanged fixed 10x10 map, ordered path,
one wave of 20 identical enemies, and recommended tower placements. This is a
search/results viewer, not an interactive gameplay mode.

First verify Tk for the **same Python interpreter** you will use to launch:

```sh
python3 -m tkinter
```

A small Tk demonstration window should open; close it before launching the app.
See the [official Tkinter setup documentation](https://docs.python.org/3/library/tkinter.html).
On macOS/Windows, use a Python distribution with Tcl/Tk support (the official
python.org installers include it; enable Tcl/Tk when the installer offers that
option). On Linux, install your distribution's Tk package for your Python, for
example `sudo apt install python3-tk` on Debian/Ubuntu. Custom Python builds may
need Tcl/Tk enabled when building Python. Tk is not installed via
`pip install tkinter`. Recreate a virtual environment with the Tk-enabled
interpreter if needed.

From the repository on macOS/Linux:

```sh
PYTHONPATH=src python3 -m tower_defense_optimizer.gui
```

After editable installation, use the dedicated command:

```sh
tower-defense-optimizer-ui
```

Or launch with the installed environment's interpreter on Windows:

```powershell
.venv\Scripts\python.exe -m tower_defense_optimizer.gui
```

If Tk is missing or no graphical desktop is available, use the CLI unchanged:

```sh
PYTHONPATH=src python3 -m tower_defense_optimizer --algorithm all --max-expanded-states 4
```

The launcher reports normal missing-Tk/display errors with that fallback.
Some native Tk builds can abort before Python can handle a missing desktop;
use CLI mode on headless hosts or restricted macOS runners.

Choose BFS, A* Algorithm, Simple Hill Climbing, or **Compare all three**. The
controls set identical per-algorithm limits on the single fixed scenario. Defaults
are 32 explored states, 3 seconds per algorithm, and 5 trace stages. Zero state/time
allowances are supported; blank time means no deadline. GUI traces are capped at
20 stages; zero disables retention. Trace visibility can be toggled after a run
without running another search. Default caps make this a short demonstration,
not a promise of an optimal defense.

The comparison table shows exactly six measures: enemies defeated, enemies
escaped, base health left, execution time in seconds, explored states, and peak
traced Python memory in KiB (1024 bytes). Spending is never a performance measure.
Select a result row to see its tower types/cells, termination reason, full
explanation, and matching grid. A horizontal scrollbar preserves table labels on
narrow windows; the split between map and details can be dragged. Resizing scales
the grid and wraps the explanatory text. Colored cells also carry distinct symbols,
and the grid includes row/column labels and a legend.

**Show short teaching trace** expands the selected result's existing classroom
formatter: `1. BFS`, `2. A* Algorithm`, or `3. Simple Hill Climbing`, with consecutive
`Stage 0`, `Stage 1`, ... grids and A* g/h/f where relevant. In compare mode, rows
retain that order. BFS/A* traces show expansion order; hill climbing shows its
accepted path and best-neighbor comparisons. Truncation and disabled/zero-limit
traces are reported explicitly. These are configurations, not wave animation.

`ui_model.py` handles Tk-independent validation, grid tiles, six-measure formatting,
and original result/trace presentation. `gui.py` only dispatches `run_searches`
from a single background worker and displays its `SearchResult` values. Tk widgets
are accessed exclusively on the main thread through queue polling. Controls are
disabled during a run so measurement sessions cannot overlap; earlier completed
results stay visible until new results arrive. Closing the window exits the UI;
it does not save partial search work. No simulator or search logic lives in the
callbacks. The common lexicographic objective, legality rules, fallback, counting,
measurement boundaries, and resource-limit meanings remain unchanged.

UI activity can contribute Python allocations during the shared process-wide
tracemalloc session, and polling/resizing can affect elapsed time. UI measurements
are observations, not a controlled benchmark; use CLI `--benchmark` for repeatable
measurement runs. Peak memory is Python allocations, not all process memory/RSS.
Time checks remain cooperative. A limited recommendation is best-so-far, while
hill climbing can stop at a local optimum; it does not claim global optimality.

### Desktop smoke and manual checklist

The normal automated suite is headless. With Tk and a graphical desktop, also run:

```sh
PYTHONPATH=src python3 tests/gui_smoke.py
```

This opens and closes a real window automatically, runs compare-all with four
expansions and two retained trace stages, and checks worker completion, metrics,
row selection, grid tiles, trace expansion/collapse, A* scores, resizing, validation,
and shutdown. Restricted macOS environments may need desktop access for this
command; a sandbox abort during native application registration is not a Python
assertion failure.

For manual verification:

1. Launch the UI; check the empty 10x10 grid, spawn/base, path and build-site legend.
2. Run each single algorithm, then compare all three with the same limits. While
   running, resize the window and confirm it stays responsive and Run is disabled.
3. Select each comparison row. Confirm the six measures, tower names/cells, matching
   grid, algorithm explanation, and termination reason are readable.
4. Expand the teaching trace. Check numbered headings, Stage labels, grid rows,
   A* g/h/f, and the hill-climbing acceptance/stop explanation. Collapse it again.
5. Try four expansions and two trace stages, then zero expansions/time or trace
   stages. Confirm best-so-far/limit labels and no invented trace stages.
6. Enter a negative state limit, `nan` time, or 21 trace stages; confirm an actionable
   error and that a corrected input can run. Close and reopen the window.
7. On a Python without Tk, confirm the GUI explains the requirement and the CLI
   command above still works.

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

## Repeatable benchmarks

Benchmark mode runs all three existing algorithms; it adds no search algorithm
and does not change their semantics. A small bounded workflow from the repository:

```sh
PYTHONPATH=src python3 -m tower_defense_optimizer --benchmark --max-expanded-states 4 --repeats 2 --output benchmark.json
python3 -m json.tool benchmark.json
```

The normal installed module/console entry point accepts the same flags. To
compare a different shared budget/tower limit or apply a deadline:

```sh
PYTHONPATH=src python3 -m tower_defense_optimizer --benchmark --budget 300 --max-towers 2 --max-expanded-states 4 --time-limit 1 --repeats 2 --output benchmark-limited.json
```

Each repeat runs **BFS, A* Algorithm, Simple Hill Climbing**, in that fixed order,
with no warmups. Every call receives the exact same immutable `Scenario` and
`SearchLimits`, including map dimensions, ordered path, build sites, wave size,
enemy health/speed/leak damage, timing, full tower definitions, initial base
health, credits available, and tower count. All enemies use the homogeneous wave
model from the shared simulator. Resource allowances reset per algorithm and per
repeat. The fixed order is deterministic but may have order/cache effects;
these small runs are demonstrations, not rigorous hardware comparisons.

`--repeats` must be at least one and defaults to one. Benchmark mode always runs
all three; `--algorithm all` is allowed, other algorithm selections are rejected.
`--output FILE` writes JSON and is optional; terminal reporting is always shown.
Both `--output` and `--repeats` require `--benchmark`. Traces are disabled equally
(`max_trace_steps=0`), and `--trace` is rejected; `--trace-steps` has no effect in
benchmark mode. Use normal CLI mode for classroom traces.

The terminal report prints every run's tower configuration, defeated/escaped
counts, remaining base health, elapsed seconds, explored states, peak traced
Python bytes, termination reason, explicit `limit stopped` flag, and result scope.
It then shows operational medians per algorithm. Gameplay outcomes are never
averaged or combined across configurations. JSON summary groups preserve the
configuration, its exact outcome, termination reason, and contributing run indices.
There is no overall winner or ranking by coins spent.

A resource-limited BFS/A* result is `best_evaluated_so_far`; a resource-limited
hill-climbing result is `current_accepted_best_so_far`, which excludes a partially
scanned neighborhood. Normal hill-climbing termination means a local optimum
under one-placement moves, not a global optimum. Frontier exhaustion is labeled
separately. Identical expansion budgets do not imply identical simulation counts:
hill climbing evaluates neighbors that do not count as explored. Explored always
means unique states admitted for expansion, including initial/terminal states.

Measurements reuse the algorithms' unchanged `RunInstrumentation` boundaries:
initialization, fallback simulation, search, simulations and bookkeeping are
inside a fresh context per run; result construction, benchmark metadata, summaries,
formatting and export are outside. `perf_counter` elapsed time and peak
`tracemalloc` bytes are **hardware/runtime-sensitive**. Peak bytes cover traced
Python allocations, not all process memory, native allocations or RSS. Previously
allocated report/results retained between runs are outside the next fresh tracer.
External tracing is rejected by the shared measurement contract. Cooperative time
limits can overrun by one operation and can change configurations across repeats;
equal deadlines do not promise equal progress or repeatable gameplay results.

JSON schema version 1 contains:

- `metadata`: Python version/implementation, platform/machine, UTC report creation
  timestamp, fixed order, repeat count, measurement notes, and SHA256 hashes of
  every package Python module plus their aggregate implementation identity.
- `settings`: the complete scenario and limits, with `settings_sha256` identifying
  the canonical settings. Build sites and tower definitions have stable ordering;
  the path retains traversal order. Different search budgets produce different IDs.
- `runs`: sequential run index, repeat/order, algorithm name/version (the aggregate
  source hash, including shared game logic), shared settings ID, exact placements,
  gameplay outcome, operational metrics, termination reason, limit flag and scope.
- `summary`: operational medians and separate configuration/outcome groups for
  each algorithm. Run indices refer to the original per-run records.

The timestamp and operational observations intentionally vary; source/settings
hashes and gameplay outcomes are repeatable for identical code/settings without
binding time limits. The source hashes identify uncommitted code too. This is
provenance for the current checkout, not a promise of cross-version performance.
No sample timing or memory numbers are asserted in this workflow.

Programmatic use accepts one shared configuration, not separate per-algorithm
budgets:

```python
from tower_defense_optimizer.benchmark import run_benchmark, export_json, format_benchmark
from tower_defense_optimizer.search_common import SearchLimits

report = run_benchmark(limits=SearchLimits(4, None, 0), repeats=2)
export_json(report, "benchmark.json")
print(format_benchmark(report))
```

## Test and development tooling

The standard-library `unittest` runner is the test tool. The explicit discovery
command below is the project's test configuration and requires no test plugin.

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The smoke test imports the package, calls `main([])`, and checks its help output and
successful return code. From an uninstalled macOS/Linux checkout, the equivalent
full headless suite is:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Optional Ruff settings live in `pyproject.toml`. To run the configured lint check
with your development interpreter:

```sh
python3 -m pip install ruff
python3 -m ruff check src tests
```

Ruff is a development tool, not a runtime/test dependency. The lint selection
is explicitly `E4`, `E7`, `E9`, and `F` (core correctness checks), so expanded
upstream defaults do not trigger unrelated style or exception-contract changes.
This pass uses Ruff 0.17.4; broader opt-in rules are not a release gate. There is
no configured type checker or mandatory formatter; do not confuse optional annotation checking
with the standard-library test suite. The separate desktop smoke command is
`PYTHONPATH=src python3 tests/gui_smoke.py` and requires a graphical desktop.

## Phase status

The shared game contracts, deterministic simulator, three search algorithms,
bounded teaching traces, application service, command-line integration, small
repeatable benchmark reports, and an optional desktop UI are implemented and
tested. The integration suite uses a tiny deterministic scenario
to verify common results, legal recommendations, simulator consistency, outcome
accounting, repeatability, equivalent limits, CLI output/errors, and UI-independent
presentation. Desktop startup checks are separate from headless tests. A large
benchmark suite remains outside this phase.

## Troubleshooting and known limitations

| Symptom | Action |
| --- | --- |
| `No module named tower_defense_optimizer` | Run from the repository with `PYTHONPATH=src`, or install with the same interpreter using `python -m pip install -e .`. PowerShell users should use the installed environment commands above. |
| Console command not found | Use the environment's Python with `-m tower_defense_optimizer`; the command is installed inside that environment's scripts directory. |
| A run takes too long or uses substantial memory | Lower `--max-expanded-states` and/or set `--time-limit`. Trace truncation is not a search or memory cap. |
| Result stopped at `max_expanded_states` / `time_limit` | This is a resource-limited best-so-far result. Increase the relevant allowance if needed; no gameplay-optimality conclusion follows. |
| Benchmark JSON cannot be written | Choose `--output` in an existing writable directory. JSON export replaces an existing file at that path, so use a new filename to preserve earlier reports. |
| Invalid settings / exit code 2 | Read the argparse error. State/trace caps and budget are nonnegative; max towers and benchmark repeats are at least 1; time is finite and nonnegative. |
| External memory tracing / overlapping search error | Stop the external `tracemalloc` session or overlapping run. Each search must own its fresh tracer. |
| No trace stages / omitted stages | Check `--trace`, capacity, and zero resource limits. Retained stages are a prefix; the final recommendation may be outside it. |
| Tk missing, display unavailable, or native Tk startup abort | Follow the optional UI setup section and use a desktop session. The CLI and headless tests work without Tk. |
| Custom scenario fails wave-time validation | Increase `max_wave_seconds` to cover all quantized spawns plus path travel; shortening the wave does not silently count unfinished enemies as escaped. |

This release intentionally has no extra maps, enemy types, additional waves,
live gameplay, tower removal/upgrades, splash damage, random restarts, fourth
search algorithm, or charts. The default map is not balance-tuned. BFS/A* can
retain large frontiers; a state limit is not a hard memory cap. The hill-climbing
variant chooses the best neighbor after a full scan and can stop on plateaus.
Time checks are cooperative, not a preemptive deadline. Measurements depend on
Python, hardware, runtime activity and tracing overhead; UI measurements are less
controlled than CLI benchmark runs. Full simulator event logs are retained for
recommendations and can also consume memory. No Python-version/OS compatibility
matrix has been measured: validation on one host is not a cross-platform claim.
The teaching PDF is absent from this checkout; the project uses the requested
numbered presentation convention rather than claiming a verified transcription.

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

A small configuration example (structural, not a timing measurement):

```text
Stage 0: empty configuration                 depth 0
Stage 1: Arrow at (1, 2)                     depth 1
Stage 2: Cannon at (1, 2)                    depth 1
```

Stage 2 replaces the displayed candidate because BFS is visiting another branch;
it does not remove the Arrow from a single evolving defense. All one-tower states
are considered before any two-tower state. Each actual CLI stage renders the full
grid and its simulated outcome; placement depth is not a measure of defense quality.

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

For the default four-tower target, a configuration containing Arrow at `(1, 2)`
and Cannon at `(1, 6)` has `g=2`, `h=2`, `f=4`. The empty state has `g=0`, `h=4`,
`f=4`; any one-tower state has `g=1`, `h=3`, `f=4`. These are search-depth scores,
not defeated-enemy estimates. A legal one-tower state may outperform a deeper
state in gameplay, and both remain eligible recommendations.

The frontier is a min-heap retaining multiple equal-priority entries with unique
sequence numbers, not a dictionary keyed by `f`. Best-known `g` is stored by
canonical configuration; equal/worse rediscoveries are ignored, and stale popped
entries are skipped before evaluation/counting/tracing. Strict improvements are
supported by the bookkeeping, although all real routes to a configuration here
have identical unit cost. Equal `f` values do not overwrite states, and the
frontier is retained across expansions.

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

For example, from an empty defense, placing a Sniper at `(3, 4)` is a legal
one-placement neighbor. It becomes `Stage 1` only if it is the deterministically
selected best neighbor and strictly improves the initial outcome. From there,
placing an Arrow at `(1, 6)` is a possible next neighbor; it becomes `Stage 2`
only under the same strict rule. If the best legal neighbor has an equal outcome,
the current Sniper-only state is retained and search stops, even if adding two
towers together could help. This is why a
plateau can hide a better configuration beyond one move. These are structural
examples, not a claim that every limited run accepts those moves.

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
