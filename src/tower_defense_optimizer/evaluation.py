"""Shared gameplay objective, independent of spending and search/runtime metrics."""

from .simulator import SimulationResult


def objective_key(result: SimulationResult) -> tuple[int, int]:
    """Maximize defeated enemies, then remaining base health lexicographically."""
    return result.enemies_defeated, result.base_health_remaining


def compare_outcomes(left: SimulationResult, right: SimulationResult) -> int:
    """Return 1 if left is better, -1 if worse, and 0 for an objective tie."""
    left_key, right_key = objective_key(left), objective_key(right)
    return (left_key > right_key) - (left_key < right_key)
