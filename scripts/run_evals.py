#!/usr/bin/env python3
"""CLI entry point for the eval harness.

Usage:
    python scripts/run_evals.py --suite smoke
    python scripts/run_evals.py --suite full
    python scripts/run_evals.py --suite full --judge   # requires ANTHROPIC_API_KEY

Exit codes:
    0 — accuracy >= regression threshold
    1 — accuracy dropped below threshold
    2 — argument error
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.runner import EvalRunner


def main() -> None:
    parser = argparse.ArgumentParser(description="Run clinical governance eval harness.")
    parser.add_argument(
        "--suite", choices=["smoke", "full"], default="smoke",
        help="'smoke' = first 10 cases (fast, CI); 'full' = all 25 cases.",
    )
    parser.add_argument(
        "--judge", action="store_true",
        help="Enable LLM-as-judge (requires ANTHROPIC_API_KEY, full suite only).",
    )
    parser.add_argument(
        "--output", default=None,
        help="Write JSON report to this file path.",
    )
    args = parser.parse_args()

    runner = EvalRunner(run_llm_judge=args.judge)
    report = runner.run(suite=args.suite)
    result = report.to_dict()

    if args.output:
        Path(args.output).write_text(json.dumps(result, indent=2))
        print(f"Report written to {args.output}", file=sys.stderr)

    print(json.dumps(result, indent=2))

    print(f"\n--- Eval summary ({args.suite} suite) ---", file=sys.stderr)
    print(f"  Accuracy:           {result['accuracy']:.1%} "
          f"(threshold {result['regression_threshold']:.0%})", file=sys.stderr)
    print(f"  False negative rate: {result['false_negative_rate']:.1%}", file=sys.stderr)
    print(f"  Brier score:         {result['brier_score']}", file=sys.stderr)
    print(f"  Mean latency:        {result['mean_latency_ms']} ms", file=sys.stderr)

    if not result["regression_passed"]:
        print(
            f"\nREGRESSION: accuracy {result['accuracy']:.1%} is below "
            f"threshold {result['regression_threshold']:.0%}",
            file=sys.stderr,
        )
        sys.exit(1)

    print("  ✓ Regression gate passed.", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
