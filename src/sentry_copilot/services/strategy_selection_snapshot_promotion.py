"""Pure construction of selection snapshots from eligible vision proposals and trusted identity."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from sentry_copilot.domain.evidence import EvidenceRecord
from sentry_copilot.domain.identifiers import SessionId, SessionParticipantId
from sentry_copilot.domain.strategy_selection import (
    ParticipantField,
    PlayerTag,
    StrategySelectionParticipant,
    StrategySelectionSnapshot,
)
from sentry_copilot.vision.strategy_selection_promotion import StrategySelectionPromotionProposal


class StrategySelectionExplicitIdentity(BaseModel):
    """Trusted identity facts for one explicit selection-screen row."""

    model_config = ConfigDict(frozen=True)

    session_player_id: SessionParticipantId
    selection_row: int = Field(ge=1, le=4)
    player_tag: PlayerTag
    display_name: str | None = None
    evidence: EvidenceRecord

    @field_validator("session_player_id", "display_name")
    @classmethod
    def strings_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("identity strings cannot be blank")
        return value


def promote_explicit_strategy_identities(
    proposal: StrategySelectionPromotionProposal,
    identities: tuple[StrategySelectionExplicitIdentity, ...],
    *,
    session_id: SessionId,
    ruleset_id: str,
    captured_at: AwareDatetime,
    strategy_evidence: EvidenceRecord,
) -> StrategySelectionSnapshot:
    """Construct an unfrozen snapshot without writing state or inferring runtime facts."""
    if not proposal.eligible:
        raise ValueError("strategy promotion proposal is not eligible")
    if proposal.eligible != proposal.precheck.strategy_set_complete:
        raise ValueError("promotion proposal eligibility disagrees with its precheck")
    claims_by_row = _index_strategy_claims(proposal.strategy_claims)
    _require_exact_rows(claims_by_row, "proposal")
    identities_by_row = _index_identities(identities)
    _require_exact_rows(identities_by_row, "identity")
    if set(claims_by_row) != set(identities_by_row):
        raise ValueError("proposal and identity selection rows must match")

    participants = tuple(
        _participant(claims_by_row[row], identities_by_row[row], strategy_evidence)
        for row in sorted(claims_by_row)
    )
    return StrategySelectionSnapshot(
        session_id=session_id,
        ruleset_id=ruleset_id,
        captured_at=captured_at,
        participants=participants,
        frozen=False,
        evidence=(strategy_evidence,) + tuple(identity.evidence for identity in identities),
    )


def _require_exact_rows(values: Mapping[int, object], source: str) -> None:
    if set(values) != {1, 2, 3, 4}:
        raise ValueError(f"{source} evidence must contain exactly selection rows 1, 2, 3, 4")


def _index_strategy_claims(claims: tuple[tuple[int, str], ...]) -> dict[int, str]:
    if len(claims) != 4:
        raise ValueError("proposal must contain exactly four strategy claims")
    result: dict[int, str] = {}
    for selection_row, strategy_id in claims:
        if selection_row in result:
            raise ValueError("proposal strategy claim rows must be unique")
        if not strategy_id.strip():
            raise ValueError("proposal strategy claims must have non-empty strategy IDs")
        result[selection_row] = strategy_id
    _require_exact_rows(result, "proposal")
    return result


def _index_identities(
    identities: tuple[StrategySelectionExplicitIdentity, ...],
) -> dict[int, StrategySelectionExplicitIdentity]:
    result: dict[int, StrategySelectionExplicitIdentity] = {}
    for identity in identities:
        if identity.selection_row in result:
            raise ValueError("identity selection rows must be unique")
        result[identity.selection_row] = identity
    return result


def _participant(
    strategy_id: str,
    identity: StrategySelectionExplicitIdentity,
    strategy_evidence: EvidenceRecord,
) -> StrategySelectionParticipant:
    field_evidence = {
        ParticipantField.PLAYER_TAG: identity.evidence,
        ParticipantField.STRATEGY: strategy_evidence,
    }
    if identity.display_name is not None:
        field_evidence[ParticipantField.DISPLAY_NAME] = identity.evidence
    return StrategySelectionParticipant(
        session_player_id=identity.session_player_id,
        selection_row=identity.selection_row,
        player_tag=identity.player_tag,
        display_name=identity.display_name,
        strategy_id=strategy_id,
        field_evidence=field_evidence,
    )
