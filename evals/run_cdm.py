"""Run the MIMIC-CDM evaluation, or an unscored demo on real MIMIC notes.

Two modes
---------
1. SCORED BENCHMARK (default) -- Meditron/mock on labeled CDM cases, graded by
   the Hager 4-axis rubric. Produces F1 scores.

    python evals/run_cdm.py --model mock        # CI default; deterministic 1.000
    python evals/run_cdm.py --model meditron    # local Meditron-7B via Ollama

2. UNSCORED DEMO -- Meditron reads REAL de-identified MIMIC-IV *demo* discharge
   notes and proposes diagnosis/treatment/labs/procedures. The demo notes have
   no gold labels, so NOTHING is scored -- this is a qualitative demonstration
   that the agent runs on real, legitimately-accessed PhysioNet data.

    python evals/run_cdm.py --model meditron --demo-notes /path/to/mimic-demo

The 'meditron' backend is LOCAL-ONLY. Prerequisites:
    brew install ollama          # or see https://ollama.com/download
    ollama serve                 # start the local server (separate terminal)
    ollama pull meditron:7b      # ~3.8 GB, one-time
    pip install ollama           # the Python client

Demo notes: download the free subset from
    https://physionet.org/content/mimic-iv-demo/   (free account, no CITI)
The labeled, DUA-gated MIMIC-IV-Ext-CDM (CITI + signed DUA) is the legitimate
*scored* source; it drops into mode 1 via the cdm dataset's --notes-dir later.

RESEARCH USE ONLY -- Meditron's authors recommend against clinical deployment.
PHI: read-only, no patient writes, governance invariant committed == 0 holds.
Note text is never logged; only note_id and model output are shown.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Make evals/ and evidence_pipeline/ importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.mimic_cdm_eval import run_governance_cdm_eval


def _run_scored(model: str, as_json: bool) -> int:
    report = run_governance_cdm_eval(
        use_mock=(model == "mock"), backend=model,
    )
    if as_json:
        print(json.dumps(report.summary(), indent=2))
    else:
        report.print_summary()
        if model == "mock":
            print(
                "\n  NOTE: mock backend echoes gold labels -> 1.000 by "
                "construction. This verifies the harness, not model quality.\n"
                "  For a real measurement: python evals/run_cdm.py --model meditron"
            )
    return 0 if report.passed else 1


def _run_demo(model: str, notes_dir: str, limit: int, show_preview: bool) -> int:
    """Unscored demonstration on real MIMIC demo notes (no gold labels)."""
    from evals.cdm_agent import make_backend
    from evals.demo_notes import DemoNotesLoader

    if model != "meditron":
        print("  Demo mode is intended for --model meditron (real model on real "
              "notes). The mock backend has no gold labels to echo here.")
    loader = DemoNotesLoader(notes_dir)
    notes = loader.load(limit=limit)
    if not notes:
        print(f"  No notes found in {notes_dir}.")
        return 1

    agent = make_backend(model, gold_lookup={})

    print("\nMIMIC-IV Demo — Unscored CDM Demonstration (NOT a benchmark)")
    print("=" * 66)
    print(f"  backend : {model}   notes: {len(notes)}   source: {notes_dir}")
    print("  No gold labels -> no scoring. Showing model proposals only.")
    print("=" * 66)

    for note in notes:
        resp = agent.propose(note.note_id, note.text)
        print(f"\n  note_id: {note.note_id}")
        if show_preview:
            print(f"    preview : {note.preview()}")
        print(f"    diagnosis (ICD-10) : {resp.proposed_icd or '—'}")
        print(f"    treatment (RxNorm) : {resp.proposed_rxnorm or '—'}")
        print(f"    labs (LOINC)       : {resp.proposed_loinc or '—'}")
        print(f"    procedures (CPT)   : {resp.proposed_cpt or '—'}")

    print("\n  (Demonstration only — outputs are not graded against any key.)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="MIMIC-CDM model benchmark (scored) or demo-notes run (unscored)")
    parser.add_argument(
        "--model", default="mock", choices=["mock", "meditron"],
        help="Backend: 'mock' (deterministic upper bound) or 'meditron' (local).",
    )
    parser.add_argument(
        "--demo-notes", default=None, metavar="DIR",
        help="Path to real MIMIC-IV demo notes -> run UNSCORED demo instead of benchmark.",
    )
    parser.add_argument(
        "--limit", type=int, default=5,
        help="Max demo notes to run (demo mode only; default 5).",
    )
    parser.add_argument(
        "--show-preview", action="store_true",
        help="Show a short truncated note preview (operator opt-in; demo mode).",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON (scored mode).",
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s",
    )

    if args.demo_notes:
        return _run_demo(args.model, args.demo_notes, args.limit, args.show_preview)
    return _run_scored(args.model, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
