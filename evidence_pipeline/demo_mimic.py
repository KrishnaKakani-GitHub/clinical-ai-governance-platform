"""CLI demo: run the end-to-end MIMIC-IV pipeline and print the outcome metric.

Usage
-----
  # With real MIMIC-IV Demo files (free PhysioNet account required):
  python evidence_pipeline/demo_mimic.py --notes-dir /path/to/mimic-iv-demo/note

  # Without MIMIC-IV files (uses synthetic notes, zero PHI):
  python evidence_pipeline/demo_mimic.py

PhysioNet MIMIC-IV Demo:
  https://physionet.org/content/mimic-iv-demo/
  Free account required. No CITI training needed for demo subset.

PHI NOTE: This script never logs raw text. All output is note IDs + LOINC codes.
"""
from __future__ import annotations

import argparse
import logging
import sys

logging.basicConfig(level=logging.WARNING,
                    format="%(levelname)s %(name)s: %(message)s")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run the MIMIC-IV evidence pipeline and print outcome metric."
    )
    parser.add_argument(
        "--notes-dir",
        default=None,
        help="Path to MIMIC-IV notes directory containing discharge.csv. "
             "Omit to use synthetic notes.",
    )
    parser.add_argument(
        "--max-notes",
        type=int,
        default=100,
        help="Maximum notes to process (default 100).",
    )
    args = parser.parse_args(argv)

    if args.notes_dir:
        from evidence_pipeline.datasets.mimic import MIMICLoader
        loader = MIMICLoader(args.notes_dir, max_notes=args.max_notes)
        notes = loader.load()
        print(f"Loaded {len(notes)} MIMIC-IV notes from {args.notes_dir}")
    else:
        from evidence_pipeline.datasets.mimic import generate_synthetic_notes
        notes = generate_synthetic_notes()
        print(f"No --notes-dir provided. Using {len(notes)} synthetic notes.")

    from evidence_pipeline.pipeline.end_to_end import run_pipeline
    metrics, gate = run_pipeline(notes)
    metrics.print_metric()

    print(f"Pending human review queue : {gate.pending_count} observations")
    print(f"Audit log entries          : {len(gate.audit_log())}")
    print()
    print("To approve an observation (human-in-the-loop):")
    print("  gate.approve('<observation_id>')")
    print()


if __name__ == "__main__":
    main(sys.argv[1:])
