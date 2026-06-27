"""Tests for evidence_pipeline/evals/product.py -- Layer 3 product evals."""
from __future__ import annotations

from evidence_pipeline.evals.product import (
    GOLDEN_DATASET,
    GoldenCase,
    ProductReport,
    run_product_eval,
)


# --- golden dataset structure ----------------------------------------------

def test_golden_dataset_not_empty() -> None:
    assert len(GOLDEN_DATASET) >= 5

def test_golden_dataset_has_required_fields() -> None:
    for case in GOLDEN_DATASET:
        assert case.case_id and case.question and case.focus
        assert case.expected_icd10 and case.expected_cui

def test_golden_dataset_covers_rare_diseases() -> None:
    rare = [c for c in GOLDEN_DATASET if c.is_rare_disease]
    assert len(rare) >= 2, "Golden dataset must include rare-disease cases"


# --- product eval grading --------------------------------------------------

def test_product_eval_runs() -> None:
    report = run_product_eval()
    assert report.n == len(GOLDEN_DATASET)

def test_icd10_accuracy_is_perfect() -> None:
    report = run_product_eval()
    assert report.icd10_accuracy == 1.0, (
        f"Expected 100% ICD-10 accuracy, got {report.icd10_accuracy:.1%}\n"
        + "\n".join(
            f"  [{r.case_id}] expected={r.expected_icd10} got={r.actual_icd10}"
            for r in report.results if not r.icd10_correct
        )
    )

def test_cui_accuracy_is_perfect() -> None:
    report = run_product_eval()
    assert report.cui_accuracy == 1.0, (
        f"Expected 100% CUI accuracy, got {report.cui_accuracy:.1%}\n"
        + "\n".join(
            f"  [{r.case_id}] expected={r.expected_cui} got={r.actual_cui}"
            for r in report.results if not r.cui_correct
        )
    )

def test_metatag_completeness_is_perfect() -> None:
    report = run_product_eval()
    assert report.metatag_completeness == 1.0, (
        f"Missing metatags:\n"
        + "\n".join(
            f"  [{r.case_id}] missing={r.missing_metatags}"
            for r in report.results if not r.metatags_complete
        )
    )

def test_overall_pass_rate_is_perfect() -> None:
    report = run_product_eval()
    assert report.overall_pass_rate == 1.0

def test_product_report_summary_keys() -> None:
    report = run_product_eval()
    s = report.summary()
    assert all(k in s for k in ["icd10_accuracy", "cui_accuracy",
                                 "metatag_completeness", "overall_pass_rate"])

def test_single_case_pnh() -> None:
    pnh = next(c for c in GOLDEN_DATASET if c.case_id == "prod_001")
    report = run_product_eval([pnh])
    assert report.results[0].icd10_correct
    assert report.results[0].cui_correct
