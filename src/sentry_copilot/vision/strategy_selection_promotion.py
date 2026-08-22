"""Vision-only proposal for promoting a structurally complete strategy set."""

from __future__ import annotations

from dataclasses import dataclass

from sentry_copilot.vision.strategy_selection_observations import (
    StrategySelectionCandidateObservation,
)
from sentry_copilot.vision.strategy_selection_precheck import (
    StrategySelectionCandidatePrecheck,
)


@dataclass(frozen=True)
class StrategySelectionPromotionProposal:
    """Evidence proposal; never an authoritative team snapshot."""

    eligible: bool
    strategy_claims: tuple[tuple[int, str], ...]
    blocking_reasons: tuple[str, ...]
    source: str
    precheck: StrategySelectionCandidatePrecheck


def propose_strategy_selection_promotion(
    observations: tuple[StrategySelectionCandidateObservation, ...],
    precheck: StrategySelectionCandidatePrecheck,
) -> StrategySelectionPromotionProposal:
    """Build a mechanical promotion proposal from an existing precheck."""
    claims = tuple(
        (observation.selection_row, observation.strategy_id)
        for observation in observations
        if observation.strategy_id is not None
    )
    reasons: list[str] = []
    if precheck.has_selection_row_conflict:
        reasons.append("invalid_selection_rows")
    if precheck.unresolved_rows:
        reasons.append("unresolved_strategy_rows")
    if precheck.no_strategy_candidate_rows:
        reasons.append("no_strategy_candidate_rows")
    if precheck.has_duplicate_strategy_conflict:
        reasons.append("duplicate_strategy_claims")
    if not precheck.strategy_set_complete:
        reasons.append("incomplete_strategy_set")
    return StrategySelectionPromotionProposal(
        eligible=precheck.strategy_set_complete,
        strategy_claims=claims,
        blocking_reasons=tuple(reasons),
        source="strategy-selection-vision-precheck",
        precheck=precheck,
    )
