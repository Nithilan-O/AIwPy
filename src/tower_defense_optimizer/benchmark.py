"""Repeatable fixed-order benchmark reporting; no search or timing logic here."""

from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import platform
from statistics import median

from .application import run_searches
from .config import DEFAULT_SCENARIO
from .domain import Scenario
from .search_common import SearchLimits, TerminationReason


SCHEMA_VERSION = 1
RUN_ORDER = ("BFS", "A* Algorithm", "Simple Hill Climbing")
_LIMIT_REASONS = {TerminationReason.MAX_EXPANDED_STATES, TerminationReason.TIME_LIMIT}
_METRICS = ("elapsed_seconds", "states_explored", "peak_memory_bytes")


def _digest(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _settings(scenario: Scenario, limits: SearchLimits) -> dict:
    """Snapshot every scenario field, including the ordered path and full wave."""
    config = asdict(scenario)
    config["buildable_cells"] = sorted(config["buildable_cells"])
    config["towers"] = sorted(config["towers"], key=lambda tower: tower["id"].value)
    # Normalize tuples/enums to plain JSON values for a round-trippable schema.
    return json.loads(json.dumps({"scenario": config, "limits": asdict(limits)}))


def _source_versions() -> dict:
    """Content hashes identify the exact local implementation, even before commit."""
    root = Path(__file__).parent
    sources = {path.name: sha256(path.read_bytes()).hexdigest()
               for path in sorted(root.glob("*.py"))}
    return {"implementation_sha256": _digest(sources), "module_sha256": sources}


def _summarize(runs: list[dict]) -> list[dict]:
    """Median operational metrics only; keep each configuration's outcomes separate."""
    summaries = []
    for algorithm in RUN_ORDER:
        rows = [row for row in runs if row["algorithm"] == algorithm]
        groups = {}
        for row in rows:
            group = {key: row[key] for key in
                     ("configuration", "outcome", "termination_reason", "limit_stopped", "result_scope")}
            key = json.dumps(group, sort_keys=True)
            if key not in groups:
                groups[key] = {**group, "run_indices": []}
            groups[key]["run_indices"].append(row["run_index"])
        summaries.append({
            "algorithm": algorithm, "run_count": len(rows),
            "median_operational_metrics": {
                name: median(row["metrics"][name] for row in rows) for name in _METRICS
            },
            "configuration_outcomes": list(groups.values()),
        })
    return summaries


def run_benchmark(
    scenario: Scenario = DEFAULT_SCENARIO,
    limits: SearchLimits = SearchLimits(max_trace_steps=0),
    *, repeats: int = 1,
) -> dict:
    """Run all three sequentially with identical immutable inputs on every repeat.

    Existing searches own fresh RunInstrumentation sessions. Metadata, summaries,
    serialization and file I/O remain outside those measurement boundaries.
    There are no warmups. Traces are disabled equally to avoid trace overhead.
    """
    if type(repeats) is not int or repeats < 1:
        raise ValueError("benchmark repeats must be an integer of at least 1")
    if limits.max_trace_steps != 0:
        raise ValueError("benchmarks require max_trace_steps=0; use normal CLI runs for traces")
    settings = _settings(scenario, limits)
    settings_id = _digest(settings)
    versions = _source_versions()
    runs = []
    for repeat in range(1, repeats + 1):
        results = run_searches("all", scenario, limits)
        if tuple(result.algorithm.value for result in results) != RUN_ORDER:
            raise ValueError("benchmark requires BFS, A*, and hill climbing in fixed order")
        for position, result in enumerate(results, 1):
            limited = result.termination_reason in _LIMIT_REASONS
            if limited:
                scope = ("current_accepted_best_so_far" if position == 3
                         else "best_evaluated_so_far")
            elif result.termination_reason is TerminationReason.LOCAL_OPTIMUM:
                scope = "local_optimum_under_one_placement_moves"
            else:
                scope = "best_evaluated_after_exhaustion"
            runs.append({
                "run_index": len(runs) + 1, "repeat": repeat, "order_in_repeat": position,
                "algorithm": result.algorithm.value, "settings_sha256": settings_id,
                "algorithm_version": versions["implementation_sha256"],
                "configuration": [{"tower_id": item.tower_id.value, "cell": list(item.cell)}
                                  for item in result.best_configuration.placements],
                "outcome": {"enemies_defeated": result.simulation_result.enemies_defeated,
                            "enemies_escaped": result.simulation_result.enemies_escaped,
                            "base_health_remaining": result.simulation_result.base_health_remaining},
                "metrics": {"elapsed_seconds": result.elapsed_seconds,
                            "states_explored": result.states_explored,
                            "peak_memory_bytes": result.peak_memory_bytes},
                "termination_reason": result.termination_reason.value,
                "limit_stopped": limited, "result_scope": scope,
            })
    return {
        "schema_version": SCHEMA_VERSION,
        "metadata": {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "platform": platform.platform(), "machine": platform.machine(),
            **versions,
            "run_order": list(RUN_ORDER), "repeats": repeats, "warmup_runs": 0,
            "measurement_note": (
                "Hardware/runtime-sensitive elapsed time and peak traced Python allocations; "
                "tracemalloc is not all process memory or RSS. Each algorithm uses its existing "
                "fresh measurement context. Reporting, metadata and export are outside it. "
                "Time limits are cooperative and can change configurations across repeats."
            ),
            "objective": ["enemies_defeated", "base_health_remaining"],
            "enemy_model": "one homogeneous wave; all enemies use the shared scenario definition",
        },
        "settings": settings, "settings_sha256": settings_id,
        "runs": runs, "summary": _summarize(runs),
    }


def export_json(report: dict, path: str | Path) -> None:
    """Export versioned JSON; preserve every per-run value and configuration."""
    Path(path).write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
                          encoding="utf-8")


def format_benchmark(report: dict) -> str:
    """Readable per-run outcomes followed by operational medians, without rankings."""
    metadata = report["metadata"]
    limits = report["settings"]["limits"]
    scenario = report["settings"]["scenario"]
    lines = [
        "Tower Defense Benchmark",
        f"UTC: {metadata['created_at_utc']}; Python: {metadata['python_version']} "
        f"({metadata['python_implementation']}); platform: {metadata['platform']}",
        f"Implementation SHA256: {metadata['implementation_sha256']}",
        f"Shared settings SHA256: {report['settings_sha256']}",
        f"Scenario: {scenario['rows']}x{scenario['columns']}; enemies={scenario['enemy_count']}; "
        f"enemy health={scenario['enemy_health']}; initial base health={scenario['base_health']}; "
        f"budget={scenario['budget']}; max towers={scenario['max_towers']}",
        "Fixed order each repeat: " + " -> ".join(metadata["run_order"]) + "; no warmups.",
        "Same full scenario and per-algorithm limits for every run: " + json.dumps(limits, sort_keys=True),
        "Objective: maximize defeated enemies, then remaining base health. Coins spent is not a metric.",
        metadata["measurement_note"],
        "Explored = unique states admitted for expansion, excluding evaluated-only neighbors.",
        "Per-run values (no gameplay outcomes are averaged):",
    ]
    for row in report["runs"]:
        outcome, metrics = row["outcome"], row["metrics"]
        lines.extend([
            f"Run {row['run_index']} (repeat {row['repeat']}): {row['algorithm']}",
            "  Towers: " + (", ".join(f"{p['tower_id']}@{tuple(p['cell'])}"
                                         for p in row["configuration"]) or "empty"),
            f"  Defeated={outcome['enemies_defeated']}; escaped={outcome['enemies_escaped']}; "
            f"remaining base health={outcome['base_health_remaining']}",
            f"  Elapsed={metrics['elapsed_seconds']:.6f} s; explored={metrics['states_explored']}; "
            f"peak Python allocations={metrics['peak_memory_bytes']} bytes",
            f"  Termination={row['termination_reason']}; limit stopped={row['limit_stopped']}; "
            f"scope={row['result_scope']}",
        ])
    lines.append("Median operational metrics per algorithm (no global-optimum claim):")
    for summary in report["summary"]:
        metrics = summary["median_operational_metrics"]
        lines.append(f"  {summary['algorithm']}: elapsed={metrics['elapsed_seconds']:.6f} s; "
                     f"explored={metrics['states_explored']}; "
                     f"peak Python allocations={metrics['peak_memory_bytes']} bytes; "
                     f"configuration/outcome groups={len(summary['configuration_outcomes'])}")
    return "\n".join(lines)
