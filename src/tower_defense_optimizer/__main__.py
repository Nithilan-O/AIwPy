"""Standard-library command line adapter for the application service."""

import argparse
from dataclasses import replace
from math import isfinite
from typing import Sequence

from .application import ALGORITHM_CHOICES, format_report, run_searches
from .config import DEFAULT_SCENARIO
from .search_common import SearchLimits


def _nonnegative_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("use a nonnegative integer") from error
    if number < 0:
        raise argparse.ArgumentTypeError("use a nonnegative integer (zero is allowed)")
    return number


def _seconds(value: str) -> float:
    try:
        number = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("use finite nonnegative seconds") from error
    if not isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("use finite nonnegative seconds")
    return number


def build_parser() -> argparse.ArgumentParser:
    """Keep argument definitions separate from execution and presentation."""
    parser = argparse.ArgumentParser(
        description="Intelligent Tower Defense Optimizer: compare deterministic searches.",
        epilog="See README.md for the fixed scenario and numbered teaching explanations.",
    )
    parser.add_argument("--algorithm", choices=ALGORITHM_CHOICES,
                        help="run one algorithm or all three in classroom order")
    parser.add_argument("--max-expanded-states", type=_nonnegative_int, default=10_000,
                        help="per-algorithm expansion cap (default: 10000)")
    parser.add_argument("--time-limit", type=_seconds, metavar="SECONDS",
                        help="per-algorithm cooperative time limit (default: none)")
    parser.add_argument("--trace", action="store_true", help="print a short teaching trace")
    parser.add_argument("--trace-steps", type=_nonnegative_int, default=5,
                        help="maximum retained stages per algorithm with --trace (default: 5)")
    parser.add_argument("--budget", type=_nonnegative_int,
                        help="override scenario credits for every algorithm")
    parser.add_argument("--max-towers", type=_nonnegative_int,
                        help="override scenario tower limit (must be at least 1)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse options, run the service, and render outside measured search work."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.algorithm is None:
        parser.print_help()
        return 0
    overrides = {name: getattr(args, name) for name in ("budget", "max_towers")
                 if getattr(args, name) is not None}
    try:
        scenario = replace(DEFAULT_SCENARIO, **overrides)
        limits = SearchLimits(args.max_expanded_states, args.time_limit,
                              args.trace_steps if args.trace else 0)
        results = run_searches(args.algorithm, scenario, limits)
    except (ValueError, RuntimeError) as error:
        parser.error(f"{error}. Check scenario/limit settings; stop external memory tracing "
                     "if a measurement session is already active.")
    print(format_report(results, scenario, limits, trace=args.trace))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
