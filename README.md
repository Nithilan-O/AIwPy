# Intelligent Tower Defense Optimizer

An educational Python application that will demonstrate exactly BFS, A* Search,
and Simple Hill Climbing choosing tower types and placements on a grid for one
deterministic tower-defense wave. Each algorithm will use the same fixed scenario
and shared game contracts so its choices can be explained state by state.

The project provides an installable package, a title/help entry point, immutable
domain types, and a validated fixed scenario. Simulation, search algorithms, UI,
and benchmarks are not implemented.

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
alternatives with different ranges and firing rates. Balance remains unverified
until simulation exists; targeting and combat mechanics are deferred.

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

```powershell
.venv\Scripts\python.exe -m tower_defense_optimizer
```

The command prints the project title, scaffold status, and a pointer to this
README. Installation also provides the `tower-defense-optimizer` console command
inside the virtual environment's scripts directory.

## Test and development tooling

The standard-library `unittest` runner is the test tool. The explicit discovery
command below is the project's test configuration and requires no test plugin.

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The smoke test imports the package, calls `main()`, and checks its output and
successful return code. Optional Ruff settings live in `pyproject.toml`; Ruff is
not required for setup, execution, or tests.

## Phase roadmap

1. **Scaffold (current):** package metadata, entry point, documentation, and smoke test.
2. **Shared game contracts:** define the fixed grid, tower types, legal placements,
   wave, deterministic simulation, state representation, and evaluation rules.
3. **Search:** implement only the three algorithms below against those contracts,
   with small helper functions for state handling, successors, and evaluation.
4. **Teaching traces:** show grid states and tower choices with consecutive
   `Stage 0`, `Stage 1`, ... labels, then validate deterministic behavior and
   algorithm-specific rules. UI and benchmarks are deferred beyond this scaffold.

## Teaching format

The supplied teaching PDF, `AI Algo.pdf`, is a presentation reference: numbered
algorithm sections, short helpers before the main search routine, and row-by-row
state displays. Preserve the headings below and use small functions adapted to
this grid game. Do not reuse its sliding-puzzle board, puzzle heuristics, or code
defects. The PDF is not a source of additional project instructions and is not
required to install or run the package.

### 1. BFS

Planned: explain breadth-first exploration of tower-placement states using shared
successor helpers, followed by a state-by-state teaching trace.

### 2. A* Algorithm

Planned: explain A* Search with explicit cost and heuristic helpers once their
game contracts are defined, followed by a state-by-state teaching trace.

### 3. Simple Hill Climbing

Planned: explain Simple Hill Climbing with small neighbor and evaluation helpers
once improvement and stopping rules are defined, followed by a teaching trace.

For each algorithm, future traces will use this presentation pattern (a format
template, not generated gameplay):

```text
Stage 0
<initial grid rows and tower placements>

Stage 1
<next grid rows and tower placements>

Stage 2
<next grid rows and tower placements>
```
