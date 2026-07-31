from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import GameMode, Phase, PlayerStatus, Server, StageType
from .identifiers import LocaleId, RulesetId, RulesetRevisionId, SessionId
from .prebattle import (
    LegacyReadySnapshotImported,
    LegacyStrategyInterpretationImported,
    PrebattleEvidenceLedger,
)
from .prebattle_migration import (
    LegacyPrebattleMigrationState,
    LegacySnapshotMigrationRecord,
)
from .rulesets import RulesetDependencyStamp, SessionRulesetContext
from .strategy_commitment import (
    StrategyCommitmentState,
    derive_strategy_commitments,
)
from .strategy_identification import (
    StrategyIdentificationBasis,
    StrategyIdentificationState,
)
from .strategy_selection import StrategySelectionSnapshot


class PlayerState(BaseModel):
    """State for one player slot.

    `avatar_visual_key` is an opaque visual fingerprint. It is never a strategy identifier.
    The strategy fields are a legacy runtime-slot cache. New strategy-selection features use
    `SessionState.strategy_selection` as their authoritative state.
    """

    model_config = ConfigDict(validate_assignment=True)

    slot: int = Field(ge=1, le=4)
    is_self: bool = False
    avatar_visual_key: str | None = None
    hp: int | None = None
    status: PlayerStatus = PlayerStatus.UNKNOWN
    strategy_id: str | None = None
    strategy_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    strategy_observed_at: datetime | None = None


class StageState(BaseModel):
    stage_type: StageType = StageType.UNKNOWN
    phase: Phase = Phase.UNKNOWN
    round_number: int | None = Field(default=None, ge=1)
    display_round: str | None = None


class SessionState(BaseModel):
    model_config = ConfigDict(validate_assignment=True, validate_default=True)

    session_id: SessionId
    server: Server = Server.CN
    locale: str = "zh_CN"
    ruleset_id: RulesetId = "unknown"
    ruleset_context: SessionRulesetContext | None = None
    mode: GameMode = GameMode.SOLO
    current_map_id: str | None = None
    stage: StageState = Field(default_factory=StageState)
    players: list[PlayerState] = Field(default_factory=list)
    strategy_selection: StrategySelectionSnapshot | None = None
    prebattle_evidence: PrebattleEvidenceLedger | None = None
    strategy_commitments: StrategyCommitmentState | None = None
    strategy_identifications: StrategyIdentificationState | None = None
    legacy_prebattle_migrations: LegacyPrebattleMigrationState | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="before")
    @classmethod
    def populate_legacy_ruleset_mirrors(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        raw_context = value.get("ruleset_context")
        if raw_context is None:
            return value
        context = SessionRulesetContext.model_validate(raw_context)
        payload = dict(value)
        expected_mirrors = {
            "ruleset_id": context.ruleset_id,
            "locale": context.locale_id.value,
        }
        for field_name, expected_value in expected_mirrors.items():
            if field_name in payload and payload[field_name] != expected_value:
                raise ValueError(
                    f"explicit legacy {field_name} does not match ruleset_context"
                )
            payload[field_name] = expected_value
        payload["ruleset_context"] = context
        return payload

    @model_validator(mode="after")
    def ruleset_context_is_consistent(self) -> SessionState:
        if self.ruleset_context is not None:
            if self.ruleset_id != self.ruleset_context.ruleset_id:
                raise ValueError("legacy ruleset_id does not match ruleset_context")
            if self.locale != self.ruleset_context.locale_id.value:
                raise ValueError("legacy locale does not match ruleset_context")
        if (
            self.strategy_selection is not None
            and self.strategy_selection.ruleset_id != self.effective_ruleset_id
        ):
            raise ValueError(
                "strategy selection ruleset_id does not match the session ruleset context"
            )
        if (
            self.strategy_selection is not None
            and self.strategy_selection.session_id != self.session_id
        ):
            raise ValueError(
                "strategy selection session_id does not match SessionState"
            )
        self._validate_prebattle_state()
        self._validate_strategy_identifications()
        self._validate_legacy_migrations()
        return self

    def _validate_prebattle_state(self) -> None:
        if self.prebattle_evidence is None:
            if self.strategy_commitments is not None:
                raise ValueError(
                    "strategy commitments require a prebattle evidence ledger"
                )
            return
        if self.prebattle_evidence.session_id != self.session_id:
            raise ValueError("prebattle evidence session_id does not match SessionState")
        if self.strategy_commitments is None:
            raise ValueError(
                "prebattle evidence requires a materialized strategy commitment state"
            )
        if self.strategy_commitments.session_id != self.session_id:
            raise ValueError(
                "strategy commitment session_id does not match SessionState"
            )
        if self.strategy_selection is None:
            raise ValueError(
                "prebattle evidence requires a strategy selection participant snapshot"
            )
        participant_ids = {
            participant.session_player_id
            for participant in self.strategy_selection.participants
        }
        evidence_participant_ids = {
            entry.session_player_id for entry in self.prebattle_evidence.entries
        }
        if not evidence_participant_ids.issubset(participant_ids):
            raise ValueError(
                "prebattle evidence participants must belong to the current session"
            )
        derived = derive_strategy_commitments(self.prebattle_evidence)
        if self.strategy_commitments != derived:
            raise ValueError(
                "strategy commitments must match effective confirmation evidence"
            )

    def _validate_strategy_identifications(self) -> None:
        identifications = self.strategy_identifications
        if identifications is None:
            return
        if identifications.session_id != self.session_id:
            raise ValueError(
                "strategy identification session_id does not match SessionState"
            )
        if self.strategy_selection is None or self.prebattle_evidence is None:
            raise ValueError(
                "strategy identifications require participant and evidence history"
            )
        participant_ids = {
            participant.session_player_id
            for participant in self.strategy_selection.participants
        }
        evidence_by_id = {
            entry.evidence_id: entry for entry in self.prebattle_evidence.entries
        }
        for record in identifications.records:
            if record.session_player_id not in participant_ids:
                raise ValueError(
                    "strategy identification participant must belong to the session"
                )
            for evidence_id in record.evidence_ids:
                evidence = evidence_by_id.get(evidence_id)
                if evidence is None:
                    raise ValueError(
                        "strategy identification evidence must exist in the ledger"
                    )
                if evidence.session_player_id != record.session_player_id:
                    raise ValueError(
                        "strategy identification evidence cannot cross participants"
                    )

    def _validate_legacy_migrations(self) -> None:
        migrations = self.legacy_prebattle_migrations
        if migrations is None:
            return
        if migrations.session_id != self.session_id:
            raise ValueError("legacy migration state session_id does not match SessionState")
        if self.strategy_selection is None:
            raise ValueError("legacy migration history requires a strategy snapshot")
        evidence_by_id = {
            entry.evidence_id: entry
            for entry in (
                self.prebattle_evidence.entries
                if self.prebattle_evidence is not None
                else ()
            )
        }
        identification_by_id = {
            record.record_id: record
            for record in (
                self.strategy_identifications.records
                if self.strategy_identifications is not None
                else ()
            )
        }
        for record in migrations.records:
            for evidence_id in record.ready_evidence_ids:
                evidence = evidence_by_id.get(evidence_id)
                if not isinstance(evidence, LegacyReadySnapshotImported):
                    raise ValueError("legacy ready migration evidence must exist")
                self._require_legacy_evidence_provenance(record, evidence)
            for evidence_id in record.strategy_evidence_ids:
                evidence = evidence_by_id.get(evidence_id)
                if not isinstance(evidence, LegacyStrategyInterpretationImported):
                    raise ValueError("legacy strategy migration evidence must exist")
                self._require_legacy_evidence_provenance(record, evidence)
            for identification_id in record.identification_record_ids:
                identification = identification_by_id.get(identification_id)
                if identification is None:
                    raise ValueError("legacy migration identification references must exist")
                if identification.basis != (
                    StrategyIdentificationBasis.LEGACY_SNAPSHOT_INTERPRETATION
                ):
                    raise ValueError("legacy migration may reference only weak legacy records")
                if not set(identification.evidence_ids).issubset(
                    record.strategy_evidence_ids
                ):
                    raise ValueError(
                        "legacy identification must use its migration's strategy evidence"
                    )

    @staticmethod
    def _require_legacy_evidence_provenance(
        record: LegacySnapshotMigrationRecord,
        evidence: LegacyReadySnapshotImported
        | LegacyStrategyInterpretationImported,
    ) -> None:
        if (
            evidence.migration_operation_id != record.operation_id
            or evidence.snapshot_fingerprint != record.snapshot_fingerprint
        ):
            raise ValueError("legacy migration evidence provenance must match its record")

    @property
    def effective_ruleset_id(self) -> RulesetId:
        if self.ruleset_context is not None:
            return self.ruleset_context.ruleset_id
        return self.ruleset_id

    @property
    def effective_locale_id(self) -> LocaleId | None:
        if self.ruleset_context is not None:
            return self.ruleset_context.locale_id
        try:
            return LocaleId(self.locale)
        except ValueError:
            return None

    @property
    def effective_ruleset_revision_id(self) -> RulesetRevisionId | None:
        if self.ruleset_context is None:
            return None
        return self.ruleset_context.ruleset_revision_id

    @property
    def ruleset_dependency_stamp(self) -> RulesetDependencyStamp | None:
        if self.ruleset_context is None:
            return None
        return self.ruleset_context.dependency_stamp

    def player(self, slot: int) -> PlayerState:
        for player in self.players:
            if player.slot == slot:
                return player
        raise KeyError(f"player slot {slot} does not exist")
