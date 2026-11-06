# Intelligent Tower Defense Optimizer

An educational Python application that will demonstrate exactly BFS, A* Search,
and Simple Hill Climbing choosing tower types and placements on a grid for one
deterministic tower-defense wave. Each algorithm will use the same fixed scenario
and shared game contracts so its choices can be explained state by state.

This phase provides only an installable package, a title/help entry point, and one
smoke test. Game rules, search algorithms, UI, and benchmarks are not implemented.
The supplied request does not specify concrete grid dimensions, tower statistics,
wave data, costs, heuristics, or shared contract signatures; those details must be
defined before the corresponding implementation phase.

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
