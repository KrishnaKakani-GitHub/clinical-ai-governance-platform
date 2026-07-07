"""Deterministic comparison: literature evidence vs. CMS coverage criteria.

Pure function, no LLM call, no network I/O. Mirrors fhir_mcp/validator.py's
role in the governance platform: a hard, code-level gate that cannot be
bypassed by an agent's summarization of the evidence.

Design note: "agreement" is computed from structured inputs only
(LiteratureEvidence.study_count / ConsensusScore.consensus_score vs.
CMSCoverageCriterion), never from an LLM's free-text judgment of whether
the sources agree. Disagreement AND thin evidence both force human
review -- they are surfaced as a distinct flagged output, never folded
silently into an aggregate agreement percentage.

PHI NOTE: Operates on condition strings and aggregate scores only.
No PHI touchpoints.
"""
from __future__ import annotations

from .models import AgreementResult, CMSCoverageCriterion, ConsensusScore, LiteratureEvidence

# Below this many studies, don't trust the consensus score either way --
# force human review regardless of the computed agreement.
MIN_STUDY_COUNT_FOR_AUTO_AGREEMENT = 5

# Consensus score at/above this threshold counts as "literature supports."
CONSENSUS_SUPPORT_THRESHOLD = 0.80


def compare_evidence_to_cms(
    literature: LiteratureEvidence,
    consensus: ConsensusScore,
    cms: CMSCoverageCriterion,
) -> AgreementResult:
    """Compare literature evidence to a CMS coverage criterion.

    Args:
        literature: PubMed-sourced study set for this condition.
        consensus:  Consensus.app claim score for this condition.
        cms:        Structured CMS NCD/LCD coverage criterion.

    Returns:
        AgreementResult. requires_human_review=True whenever the studies
        disagree with CMS OR the evidence base is too thin to trust
        (below MIN_STUDY_COUNT_FOR_AUTO_AGREEMENT), regardless of the
        raw agreement outcome.
    """
    if (
        literature.condition != cms.condition
        or consensus.claim.strip().lower() != cms.condition.strip().lower()
    ):
        # Defensive: caller wired mismatched inputs together.
        return AgreementResult(
            condition=cms.condition,
            literature_supports=False,
            cms_requires=True,
            agrees=False,
            requires_human_review=True,
            reason=(
                f"Input mismatch: literature condition={literature.condition!r}, "
                f"consensus claim={consensus.claim!r}, cms condition={cms.condition!r}"
            ),
        )

    literature_supports = consensus.consensus_score >= CONSENSUS_SUPPORT_THRESHOLD
    cms_requires = bool(cms.requires_evidence_of)
    agrees = literature_supports == cms_requires

    thin_evidence = literature.study_count < MIN_STUDY_COUNT_FOR_AUTO_AGREEMENT
    requires_human_review = thin_evidence or not agrees

    reason_parts = []
    if thin_evidence:
        reason_parts.append(
            f"only {literature.study_count} studies found "
            f"(minimum {MIN_STUDY_COUNT_FOR_AUTO_AGREEMENT} required for auto-agreement)"
        )
    if not agrees:
        reason_parts.append(
            f"literature consensus={consensus.consensus_score:.2f} "
            f"({'supports' if literature_supports else 'does not support'}) "
            f"vs. CMS requires_evidence_of={cms.requires_evidence_of!r}"
        )
    reason = "; ".join(reason_parts) or "literature and CMS coverage criterion agree"

    return AgreementResult(
        condition=cms.condition,
        literature_supports=literature_supports,
        cms_requires=cms_requires,
        agrees=agrees,
        requires_human_review=requires_human_review,
        reason=reason,
    )
