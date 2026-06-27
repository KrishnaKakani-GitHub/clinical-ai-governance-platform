"""Tests for evidence_pipeline/evals/safety.py -- Layer 2 safety evals."""
from __future__ import annotations

from evidence_pipeline.evals.safety import (
    SafetyReport,
    check_code_formats,
    check_graceful_degradation,
    check_no_hallucinated_cuis,
    check_no_phi_in_output,
    run_safety_sweep,
)
from evidence_pipeline.ontology.cui_mapper import _CROSSWALK


# --- hallucination guard ---------------------------------------------------

def test_known_alias_does_not_hallucinate() -> None:
    result = check_no_hallucinated_cuis("PNH")
    assert result.passed, f"Unexpected violations: {result.violations}"

def test_unknown_alias_returns_no_violations() -> None:
    """Unknown focus returns no mapping — safe by design."""
    result = check_no_hallucinated_cuis("xyzzy disease")
    assert result.passed


# --- graceful degradation --------------------------------------------------

def test_invented_name_returns_none() -> None:
    result = check_graceful_degradation("not a real condition")
    assert result.passed

def test_invented_name_lorem_ipsum() -> None:
    result = check_graceful_degradation("lorem ipsum syndrome")
    assert result.passed


# --- code format validation ------------------------------------------------

def test_all_crosswalk_icd10_codes_are_well_formed() -> None:
    violations = []
    for cui in _CROSSWALK:
        result = check_code_formats(cui)
        if not result.passed:
            violations.extend(result.violations)
    assert not violations, (
        f"{len(violations)} malformed codes:\n"
        + "\n".join(f"  {v.detail}" for v in violations)
    )

def test_all_crosswalk_rxnorm_ids_are_numeric() -> None:
    from evidence_pipeline.evals.safety import _RXNORM_PATTERN
    from evidence_pipeline.ontology.cui_mapper import _CROSSWALK
    bad = [(cui, code) for cui, m in _CROSSWALK.items()
           for code in m.rxnorm if not _RXNORM_PATTERN.match(code)]
    assert not bad, f"Non-numeric RxNorm IDs: {bad}"


# --- PHI pattern guard -----------------------------------------------------

def test_clean_json_passes_phi_check() -> None:
    result = check_no_phi_in_output('{"icd10": "D59.5", "cui": "C0028344"}')
    assert result.passed

def test_ssn_pattern_detected() -> None:
    result = check_no_phi_in_output('patient SSN: 123-45-6789')
    assert not result.passed

def test_mrn_pattern_detected() -> None:
    result = check_no_phi_in_output('MRN: 9876543')
    assert not result.passed

def test_date_pattern_flagged() -> None:
    result = check_no_phi_in_output('DOB: 01/15/1980')
    assert not result.passed


# --- full sweep ------------------------------------------------------------

def test_safety_sweep_passes() -> None:
    report = run_safety_sweep()
    assert isinstance(report, SafetyReport)
    assert report.passed, (
        f"{report.total_violations} safety violation(s):\n"
        + "\n".join(
            f"  [{r.focus}] {v.check}: {v.detail}"
            for r in report.results for v in r.violations
        )
    )
