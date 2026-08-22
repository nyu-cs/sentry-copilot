from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest

from sentry_copilot.domain.enums import EvidenceKind
from sentry_copilot.domain.evidence import EvidenceRecord
from sentry_copilot.domain.strategy_selection import StrategySelectionSnapshot
from sentry_copilot.services.strategy_selection_snapshot_promotion import (
    StrategySelectionExplicitIdentity,
    promote_explicit_strategy_identities,
)
from sentry_copilot.vision.local_feature_matching import LocalFeatureVisualMatchResult
from sentry_copilot.vision.strategy_selection_observations import (
    StrategySelectionCandidateObservation,
)
from sentry_copilot.vision.strategy_selection_precheck import (
    precheck_strategy_selection_candidates,
)
from sentry_copilot.vision.strategy_selection_probe import StrategySelectionProbeStatus
from sentry_copilot.vision.strategy_selection_promotion import (
    StrategySelectionPromotionProposal,
    propose_strategy_selection_promotion,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _evidence(source: EvidenceKind) -> EvidenceRecord:
    return EvidenceRecord(source=source, confidence=0.9, observed_at=NOW)


def _proposal(*rows: tuple[int, str | None]) -> StrategySelectionPromotionProposal:
    observations = tuple(
        StrategySelectionCandidateObservation(
            row,
            strategy_id,
            (
                StrategySelectionProbeStatus.MATCHED_STRATEGY
                if strategy_id is not None
                else StrategySelectionProbeStatus.UNRESOLVED_STRATEGY
            ),
            EvidenceKind.OBSERVED,
            "synthetic",
            cast(
                LocalFeatureVisualMatchResult,
                SimpleNamespace(selected_identity=None),
            ),
        )
        for row, strategy_id in rows
    )
    return propose_strategy_selection_promotion(
        observations, precheck_strategy_selection_candidates(observations)
    )


def _identities(*rows: int) -> tuple[StrategySelectionExplicitIdentity, ...]:
    return tuple(
        StrategySelectionExplicitIdentity(
            session_player_id=f"participant.{row}",
            selection_row=row,
            player_tag=f"{row:04d}",
            display_name=f"Synthetic {row}",
            evidence=_evidence(EvidenceKind.MANUAL),
        )
        for row in rows
    )


def _promote(
    identities: tuple[StrategySelectionExplicitIdentity, ...],
) -> StrategySelectionSnapshot:
    return promote_explicit_strategy_identities(
        _proposal(*tuple((row, f"strategy.synthetic.{row}") for row in range(1, 5))),
        identities,
        session_id="session.synthetic",
        ruleset_id="ruleset.synthetic",
        captured_at=NOW,
        strategy_evidence=_evidence(EvidenceKind.OBSERVED),
    )


def test_eligible_proposal_promotes_by_selection_row_not_tuple_order() -> None:
    result = _promote(tuple(reversed(_identities(1, 2, 3, 4))))
    assert [
        (item.selection_row, item.player_tag, item.strategy_id) for item in result.participants
    ] == [
        (1, "0001", "strategy.synthetic.1"),
        (2, "0002", "strategy.synthetic.2"),
        (3, "0003", "strategy.synthetic.3"),
        (4, "0004", "strategy.synthetic.4"),
    ]
    assert result.frozen is False
    assert result.expected_participant_count is None
    assert all(item.ready is None and item.is_self is None for item in result.participants)


def test_ineligible_proposal_is_rejected() -> None:
    proposal = _proposal(
        (1, "strategy.synthetic.1"),
        (2, None),
        (3, "strategy.synthetic.3"),
        (4, "strategy.synthetic.4"),
    )
    with pytest.raises(ValueError, match="not eligible"):
        promote_explicit_strategy_identities(
            proposal,
            _identities(1, 2, 3, 4),
            session_id="session.synthetic",
            ruleset_id="ruleset.synthetic",
            captured_at=NOW,
            strategy_evidence=_evidence(EvidenceKind.OBSERVED),
        )


@pytest.mark.parametrize("rows", [(1, 2, 3), (1, 2, 3, 3)])
def test_missing_or_duplicate_identity_rows_are_rejected(rows: tuple[int, ...]) -> None:
    with pytest.raises(ValueError, match="identity"):
        _promote(_identities(*rows))


def test_invalid_and_duplicate_tags_are_rejected() -> None:
    with pytest.raises(ValueError):
        StrategySelectionExplicitIdentity(
            session_player_id="participant.invalid",
            selection_row=1,
            player_tag="123",
            evidence=_evidence(EvidenceKind.MANUAL),
        )
    identities = list(_identities(1, 2, 3, 4))
    identities[1] = identities[1].model_copy(update={"player_tag": "0001"})
    with pytest.raises(ValueError, match="player_tag"):
        _promote(tuple(identities))


def test_malformed_duplicate_proposal_row_is_rejected_without_overwrite() -> None:
    valid = _proposal(*tuple((row, f"strategy.synthetic.{row}") for row in range(1, 5)))
    malformed = replace(
        valid,
        strategy_claims=(
            (1, "strategy.synthetic.a"),
            (1, "strategy.synthetic.b"),
            (2, "strategy.synthetic.c"),
            (3, "strategy.synthetic.d"),
        ),
    )
    with pytest.raises(ValueError, match="claim rows must be unique"):
        promote_explicit_strategy_identities(
            malformed,
            _identities(1, 2, 3, 4),
            session_id="session.synthetic",
            ruleset_id="ruleset.synthetic",
            captured_at=NOW,
            strategy_evidence=_evidence(EvidenceKind.OBSERVED),
        )


def test_eligibility_and_precheck_disagreement_is_rejected() -> None:
    invalid = _proposal(
        (1, "strategy.synthetic.1"),
        (2, None),
        (3, "strategy.synthetic.3"),
        (4, "strategy.synthetic.4"),
    )
    inconsistent = replace(invalid, eligible=True)
    with pytest.raises(ValueError, match="disagrees"):
        promote_explicit_strategy_identities(
            inconsistent,
            _identities(1, 2, 3, 4),
            session_id="session.synthetic",
            ruleset_id="ruleset.synthetic",
            captured_at=NOW,
            strategy_evidence=_evidence(EvidenceKind.OBSERVED),
        )
