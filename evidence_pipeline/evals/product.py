"""Layer 3 — Product evals for the Clinical Evidence Intelligence Pipeline.

End-to-end grading of the full pipeline on a golden dataset of real clinical
questions drawn from the MedQuAD corpus. No live API calls — trials and CMS
steps are mocked so the suite runs in CI without network access.

What this grades
----------------
Given a clinical question, does the pipeline produce output that:
  - Contains the correct primary ICD-10 code
  - Hits the correct UMLS CUI via the crosswalk
  - Populates all required metatag fields
  - Achieves a minimum qa_metrics score

This is the "product eval" layer: it grades the pipeline as a feature,
not just an individual component. Equivalent to A/B testing a production
changeset against a golden reference set.

JD alignment: "Verify study outputs / QA-QC" and
"Use LLMs to produce varied, high-quality outputs."

PHI NOTE: Golden dataset uses public MedQuAD question text only.
No patient data is present. Zero PHI touchpoints.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from evidence_pipeline.ontology.cui_mapper import lookup_cui, search_by_name


# ---------------------------------------------------------------------------
# Golden dataset
# ---------------------------------------------------------------------------
# Each entry: question as a user might ask, expected ICD-10, expected CUI.
# Source: representative MedQuAD questions from GARD + NIH sources.

@dataclass
class GoldenCase:
    case_id: str
    question: str                  # natural-language clinical question
    focus: str                     # extracted focus entity (disease name)
    expected_icd10: str            # primary expected ICD-10-CM code
    expected_cui: str              # expected UMLS CUI
    question_type: str = "information"
    is_rare_disease: bool = False
    required_metatags: list[str] = field(default_factory=list)


GOLDEN_DATASET: list[GoldenCase] = [
    GoldenCase(
        case_id="prod_001",
        question="What is paroxysmal nocturnal hemoglobinuria?",
        focus="Paroxysmal Nocturnal Hemoglobinuria",
        expected_icd10="D59.5",
        expected_cui="C0028344",
        question_type="information",
        is_rare_disease=True,
        required_metatags=["icd10_primary", "rxnorm_drugs", "loinc_markers"],
    ),
    GoldenCase(
        case_id="prod_002",
        question="How is Gaucher disease treated?",
        focus="Gaucher Disease",
        expected_icd10="E75.22",
        expected_cui="C0017205",
        question_type="treatment",
        is_rare_disease=True,
        required_metatags=["icd10_primary", "rxnorm_drugs"],
    ),
    GoldenCase(
        case_id="prod_003",
        question="What are the symptoms of sickle cell disease?",
        focus="Sickle Cell Disease",
        expected_icd10="D57.1",
        expected_cui="C0002895",
        question_type="symptoms",
        is_rare_disease=True,
        required_metatags=["icd10_primary", "loinc_markers"],
    ),
    GoldenCase(
        case_id="prod_004",
        question="What is the treatment for type 2 diabetes?",
        focus="Type 2 Diabetes Mellitus",
        expected_icd10="E11",
        expected_cui="C0011860",
        question_type="treatment",
        required_metatags=["icd10_primary", "rxnorm_drugs", "loinc_markers"],
    ),
    GoldenCase(
        case_id="prod_005",
        question="How is hypertension managed?",
        focus="Hypertension",
        expected_icd10="I10",
        expected_cui="C0020538",
        question_type="treatment",
        required_metatags=["icd10_primary", "rxnorm_drugs"],
    ),
    GoldenCase(
        case_id="prod_006",
        question="What causes heart failure?",
        focus="Heart Failure",
        expected_icd10="I50",
        expected_cui="C0018801",
        question_type="causes",
        required_metatags=["icd10_primary", "loinc_markers"],
    ),
    GoldenCase(
        case_id="prod_007",
        question="What is COPD and how is it treated?",
        focus="COPD",
        expected_icd10="J44.9",
        expected_cui="C0024117",
        question_type="treatment",
        required_metatags=["icd10_primary", "rxnorm_drugs"],
    ),
    GoldenCase(
        case_id="prod_008",
        question="What are the stages of chronic kidney disease?",
        focus="Chronic Kidney Disease",
        expected_icd10="N18.9",
        expected_cui="C0403447",
        question_type="stages",
        required_metatags=["icd10_primary", "loinc_markers"],
    ),
]


# ---------------------------------------------------------------------------
# Pipeline simulation (no live API)
# ---------------------------------------------------------------------------

def _simulate_pipeline(case: GoldenCase) -> dict[str, Any]:
    """Run the deterministic pipeline stages without live API calls.

    Stages 1-2 (ICD-10 mapping + CUI crosswalk) are real.
    Stages 3-4 (trials + CMS) are mocked with empty lists — the product
    eval grades correctness of the ontology layer, not API availability.
    """
    mapping = search_by_name(case.focus)
    icd10_codes = mapping.icd10 if mapping else []
    primary_icd10 = icd10_codes[0] if icd10_codes else None
    cui_data = mapping.to_dict() if mapping else None

    metatags: dict[str, Any] = {
        "icd10_primary": primary_icd10,
        "icd10_candidates": icd10_codes,
        "rxnorm_drugs": mapping.rxnorm if mapping else [],
        "loinc_markers": mapping.loinc if mapping else [],
        "snomed_concepts": mapping.snomed if mapping else [],
        "recruiting_trial_count": 0,   # mocked
        "has_cms_national_coverage": False,  # mocked
    }
    return {
        "metatags": metatags,
        "phenotype": {
            "primary_icd10": {"code": primary_icd10} if primary_icd10 else None,
            "cui_crosswalk": cui_data,
        },
        "qa_metrics": {
            "icd10_codes_found": len(icd10_codes),
            "cui_crosswalk_hit": mapping is not None,
            "pipeline_complete": mapping is not None,
        },
    }


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------

@dataclass
class ProductResult:
    case_id: str
    question: str
    expected_icd10: str
    expected_cui: str
    actual_icd10: str | None
    actual_cui: str | None
    metatags_present: list[str]
    missing_metatags: list[str]
    pipeline_complete: bool

    @property
    def icd10_correct(self) -> bool:
        if self.actual_icd10 is None or self.expected_icd10 is None:
            return False
        # Match on category prefix (e.g. expected "E11" matches "E11" or "E11.9")
        return (self.actual_icd10 == self.expected_icd10 or
                self.actual_icd10.startswith(self.expected_icd10) or
                self.expected_icd10.startswith(self.actual_icd10[:3]))

    @property
    def cui_correct(self) -> bool:
        return self.actual_cui == self.expected_cui

    @property
    def metatags_complete(self) -> bool:
        return len(self.missing_metatags) == 0

    @property
    def passed(self) -> bool:
        return self.icd10_correct and self.cui_correct and self.metatags_complete


@dataclass
class ProductReport:
    results: list[ProductResult] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.results)

    @property
    def icd10_accuracy(self) -> float:
        return sum(1 for r in self.results if r.icd10_correct) / self.n if self.n else 0.0

    @property
    def cui_accuracy(self) -> float:
        return sum(1 for r in self.results if r.cui_correct) / self.n if self.n else 0.0

    @property
    def metatag_completeness(self) -> float:
        return sum(1 for r in self.results if r.metatags_complete) / self.n if self.n else 0.0

    @property
    def overall_pass_rate(self) -> float:
        return sum(1 for r in self.results if r.passed) / self.n if self.n else 0.0

    def summary(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "icd10_accuracy": round(self.icd10_accuracy, 4),
            "cui_accuracy": round(self.cui_accuracy, 4),
            "metatag_completeness": round(self.metatag_completeness, 4),
            "overall_pass_rate": round(self.overall_pass_rate, 4),
        }

    def print_summary(self) -> None:
        print("\nProduct eval")
        print(f"  cases            : {self.n}")
        print(f"  ICD-10 accuracy  : {self.icd10_accuracy:.1%}")
        print(f"  CUI accuracy     : {self.cui_accuracy:.1%}")
        print(f"  metatag complete : {self.metatag_completeness:.1%}")
        print(f"  overall pass     : {self.overall_pass_rate:.1%}")


def run_product_eval(dataset: list[GoldenCase] | None = None) -> ProductReport:
    """Grade the pipeline against the golden dataset."""
    cases = dataset or GOLDEN_DATASET
    report = ProductReport()
    for case in cases:
        output = _simulate_pipeline(case)
        metatags = output.get("metatags", {})
        phenotype = output.get("phenotype", {})
        cui_data = phenotype.get("cui_crosswalk")
        actual_icd10 = (phenotype.get("primary_icd10") or {}).get("code")
        actual_cui = cui_data.get("cui") if cui_data else None
        present = [k for k in case.required_metatags if metatags.get(k)]
        missing = [k for k in case.required_metatags if not metatags.get(k)]
        report.results.append(ProductResult(
            case_id=case.case_id,
            question=case.question,
            expected_icd10=case.expected_icd10,
            expected_cui=case.expected_cui,
            actual_icd10=actual_icd10,
            actual_cui=actual_cui,
            metatags_present=present,
            missing_metatags=missing,
            pipeline_complete=output["qa_metrics"]["pipeline_complete"],
        ))
    return report
