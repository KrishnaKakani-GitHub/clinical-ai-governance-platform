"""Literature evidence sourcing + CMS coverage crosswalk.

PubMed-sourced study counts, Consensus.app claim scores, and a
deterministic comparison against structured CMS NCD/LCD coverage
criteria. No LLM judgment is used to decide agreement -- see
crosswalk.py's module docstring.

PHI NOTE: This package only ever handles condition strings and
aggregate study/consensus metadata. No patient identifiers or note
text pass through any module here.
"""
from __future__ import annotations
