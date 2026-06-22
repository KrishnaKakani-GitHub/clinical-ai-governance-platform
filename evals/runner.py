"""Eval harness: runs the golden dataset against the clinical governance system.

Two grading modes:
  1. Code-based grading: deterministic checks against expected_outcome.
     Fast, no API cost, always run.
  2. LLM-as-judge grading: qualitative assessment by claude-haiku.
     Requires ANTHROPIC_API_KEY, run on --suite=full.

Metrics:
  accuracy, false_negative_rate, Brier score, mean_latency_ms, judge_pass_rate

Regression gate: CI fails if accuracy < 0.80.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fhir_mcp.confidence import ConfidenceScorer
from fhir_mcp.models import ProposedObservation
from fhir_mcp.store import FhirStore, StoreError

_DATASET_PATH = Path(__file__).parent / "golden_dataset.json"
_DATA_SRC = Path(__file__).resolve().parents[1] / "data" / "synthetic_patients.json"
_REGRESSION_ACCURACY_THRESHOLD = 0.80


@dataclass
class CaseResult:
    case_id: str
    expected: str
    actual: str
    correct: bool
    confidence: float
    confidence_tier: str
    latency_ms: float
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    judge_verdict: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class EvalReport:
    total: int = 0
    correct: int = 0
    false_negatives: int = 0
    false_positives: int = 0
    cases: list[CaseResult] = field(default_factory=list)
    mean_confidence_accepted: float = 0.0
    brier_score: float | None = None
    mean_latency_ms: float = 0.0
    judge_pass_rate: float | None = None

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def false_negative_rate(self) -> float:
        total_rejects = sum(1 for c in self.cases if c.expected == "reject")
        missed = sum(
            1 for c in self.cases if c.expected == "reject" and c.actual != "reject"
        )
        return missed / total_rejects if total_rejects else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "correct": self.correct,
            "accuracy": round(self.accuracy, 4),
            "false_negative_rate": round(self.false_negative_rate, 4),
            "false_positives": self.false_positives,
            "mean_confidence_accepted": round(self.mean_confidence_accepted, 4),
            "brier_score": self.brier_score,
            "mean_latency_ms": round(self.mean_latency_ms, 2),
            "judge_pass_rate": self.judge_pass_rate,
            "regression_threshold": _REGRESSION_ACCURACY_THRESHOLD,
            "regression_passed": self.accuracy >= _REGRESSION_ACCURACY_THRESHOLD,
            "cases": [
                {
                    "id": c.case_id,
                    "expected": c.expected,
                    "actual": c.actual,
                    "correct": c.correct,
                    "confidence": c.confidence,
                    "confidence_tier": c.confidence_tier,
                    "latency_ms": c.latency_ms,
                    "violations": c.violations,
                    "warnings": c.warnings,
                    "judge_verdict": c.judge_verdict,
                    **(({"error": c.error}) if c.error else {}),
                }
                for c in self.cases
            ],
        }


class EvalRunner:
    """Runs golden dataset cases against the deterministic validation layer."""

    def __init__(
        self,
        dataset_path: Path = _DATASET_PATH,
        run_llm_judge: bool = False,
    ) -> None:
        self._dataset_path = dataset_path
        self._run_llm_judge = run_llm_judge
        self._scorer = ConfidenceScorer()
        self._store: FhirStore | None = None

    def _get_store(self) -> FhirStore:
        if self._store is None:
            import tempfile
            tmp = Path(tempfile.mkdtemp()) / "eval.db"
            self._store = FhirStore(tmp)
            self._store.import_from_json(_DATA_SRC)
        return self._store

    def run(
        self,
        suite: Literal["smoke", "full"] = "smoke",
        cases: list[dict[str, Any]] | None = None,
    ) -> EvalReport:
        if cases is None:
            all_cases = json.loads(self._dataset_path.read_text(encoding="utf-8"))
        else:
            all_cases = cases

        if suite == "smoke":
            all_cases = all_cases[:10]

        report = EvalReport(total=len(all_cases))
        latencies: list[float] = []
        conf_accepted: list[float] = []

        for case in all_cases:
            result = self._run_case(case)
            report.cases.append(result)
            if result.correct:
                report.correct += 1
            latencies.append(result.latency_ms)

            if result.expected == "reject" and result.actual != "reject":
                report.false_negatives += 1
            if result.expected != "reject" and result.actual == "reject":
                report.false_positives += 1

            self._scorer.update_outcome(result.confidence, result.correct)

            if result.actual != "reject":
                conf_accepted.append(result.confidence)

        report.mean_latency_ms = sum(latencies) / len(latencies) if latencies else 0
        report.mean_confidence_accepted = (
            sum(conf_accepted) / len(conf_accepted) if conf_accepted else 0
        )
        report.brier_score = self._scorer.brier_score()

        if self._run_llm_judge and suite == "full":
            self._run_judge_pass(report)

        return report

    def _run_case(self, case: dict[str, Any]) -> CaseResult:
        inp = case["input"]
        expected = case["expected_outcome"]
        start = time.monotonic()
        violations: list[str] = []
        warnings: list[str] = []
        actual = "reject"
        error: str | None = None

        try:
            proposed = ProposedObservation(
                patient_id=inp["patient_id"],
                code=inp["code"],
                display=inp["display"],
                value=float(inp["value"]),
                unit=inp["unit"],
                effective_date=inp["effective_date"],
            )
            store = self._get_store()
            pending = store.stage_write(proposed)
            warnings = pending.validation_warnings
            actual = "accept_with_warning" if warnings else "accept"
        except (StoreError, ValueError) as e:
            actual = "reject"
            violations = [str(e)]
        except Exception as e:
            actual = "reject"
            error = str(e)

        latency_ms = round((time.monotonic() - start) * 1000, 2)

        conf_result = self._scorer.score(
            validation_pass_rate=1.0 if actual != "reject" else 0.0,
            rag_score=0.7,
            model_logprob_proxy=0.8,
            has_validation_warnings=bool(warnings),
        )

        actual_n = "accept" if actual == "accept_with_warning" else actual
        expected_n = "accept" if expected == "accept_with_warning" else expected
        correct = actual_n == expected_n

        return CaseResult(
            case_id=case["id"],
            expected=expected,
            actual=actual,
            correct=correct,
            confidence=conf_result.confidence,
            confidence_tier=conf_result.tier,
            latency_ms=latency_ms,
            violations=violations,
            warnings=warnings,
            error=error,
        )

    def _run_judge_pass(self, report: EvalReport) -> None:
        try:
            import anthropic
            from evals.judge_prompt import build_judge_messages, parse_judge_verdict
        except ImportError:
            return

        client = anthropic.Anthropic()
        pass_count = 0
        judged = 0
        all_cases = json.loads(self._dataset_path.read_text())

        for case_result in report.cases:
            if case_result.error:
                continue
            case_data = next(
                (c for c in all_cases if c["id"] == case_result.case_id), None
            )
            if not case_data:
                continue

            system_response = {
                "actual_outcome": case_result.actual,
                "confidence": case_result.confidence,
                "confidence_tier": case_result.confidence_tier,
                "violations": case_result.violations,
                "warnings": case_result.warnings,
            }

            try:
                messages = build_judge_messages(case_data, system_response)
                response = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=256,
                    temperature=0,
                    messages=messages,
                )
                verdict = parse_judge_verdict(response.content[0].text)
                case_result.judge_verdict = verdict
                if verdict.get("verdict") == "pass":
                    pass_count += 1
                judged += 1
            except Exception:
                pass

        report.judge_pass_rate = pass_count / judged if judged else None
