from __future__ import annotations

from types import SimpleNamespace
from typing import cast

from sentry_copilot.domain.enums import EvidenceKind
from sentry_copilot.vision.local_feature_matching import LocalFeatureVisualMatchResult
from sentry_copilot.vision.strategy_selection_observations import (
    StrategySelectionCandidateObservation,
)
from sentry_copilot.vision.strategy_selection_precheck import (
    StrategySelectionCandidatePrecheck,
    precheck_strategy_selection_candidates,
)
from sentry_copilot.vision.strategy_selection_probe import StrategySelectionProbeStatus
from sentry_copilot.vision.strategy_selection_promotion import (
    StrategySelectionPromotionProposal,
    propose_strategy_selection_promotion,
)


def _observation(
    row: int, status: StrategySelectionProbeStatus, strategy: str | None
) -> StrategySelectionCandidateObservation:
    selected = SimpleNamespace(identity_id=strategy) if strategy else None
    matcher = cast(LocalFeatureVisualMatchResult, SimpleNamespace(selected_identity=selected))
    return StrategySelectionCandidateObservation(
        row, strategy, status, EvidenceKind.OBSERVED, "synthetic", matcher
    )


def _proposal(
    rows: tuple[tuple[int, StrategySelectionProbeStatus, str | None], ...],
) -> tuple[
    tuple[StrategySelectionCandidateObservation, ...],
    StrategySelectionCandidatePrecheck,
    StrategySelectionPromotionProposal,
]:
    observations = tuple(_observation(*row) for row in rows)
    precheck = precheck_strategy_selection_candidates(observations)
    return observations, precheck, propose_strategy_selection_promotion(observations, precheck)


def test_complete_precheck_is_eligible_with_ordered_claims() -> None:
    _, precheck, proposal = _proposal(
        tuple(
            (row, StrategySelectionProbeStatus.MATCHED_STRATEGY, f"strategy.synthetic.{row}")
            for row in range(1, 5)
        )
    )
    assert precheck.strategy_set_complete
    assert proposal.eligible
    assert proposal.strategy_claims == tuple(
        (row, f"strategy.synthetic.{row}") for row in range(1, 5)
    )
    assert proposal.blocking_reasons == ()


def test_unresolved_row_blocks_without_inference() -> None:
    _, _, proposal = _proposal(
        (
            (1, StrategySelectionProbeStatus.MATCHED_STRATEGY, "strategy.synthetic.a"),
            (2, StrategySelectionProbeStatus.UNRESOLVED_STRATEGY, None),
            (3, StrategySelectionProbeStatus.MATCHED_STRATEGY, "strategy.synthetic.c"),
            (4, StrategySelectionProbeStatus.MATCHED_STRATEGY, "strategy.synthetic.d"),
        )
    )
    assert not proposal.eligible
    assert "unresolved_strategy_rows" in proposal.blocking_reasons
    assert all(strategy_id is not None for _, strategy_id in proposal.strategy_claims)


def test_duplicate_strategy_and_invalid_row_block() -> None:
    _, _, proposal = _proposal(
        (
            (1, StrategySelectionProbeStatus.MATCHED_STRATEGY, "strategy.synthetic.a"),
            (1, StrategySelectionProbeStatus.MATCHED_STRATEGY, "strategy.synthetic.a"),
            (2, StrategySelectionProbeStatus.MATCHED_STRATEGY, "strategy.synthetic.b"),
            (3, StrategySelectionProbeStatus.MATCHED_STRATEGY, "strategy.synthetic.c"),
        )
    )
    assert not proposal.eligible
    assert proposal.blocking_reasons == (
        "invalid_selection_rows",
        "duplicate_strategy_claims",
        "incomplete_strategy_set",
    )


def test_proposal_contains_no_identity_fields_and_preserves_inputs() -> None:
    observations, precheck, proposal = _proposal(
        tuple(
            (row, StrategySelectionProbeStatus.MATCHED_STRATEGY, f"strategy.synthetic.{row}")
            for row in (1, 2, 4)
        )
    )
    assert proposal.precheck is precheck
    assert observations[0].selection_row == 1
    assert not any(
        hasattr(claim, field)
        for claim in proposal.strategy_claims
        for field in ("player_tag", "display_name", "session_player_id", "runtime_slot")
    )

