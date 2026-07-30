from __future__ import annotations

from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from .identifiers import (
    CatalogVersion,
    LocaleId,
    RulesetId,
    RulesetRevisionId,
)


class ValidationKind(StrEnum):
    CATALOG_STRUCTURE = "catalog_structure"
    LOCALE_RESOURCES = "locale_resources"
    ASSET_RESOLUTION = "asset_resolution"
    REPLAY_FIXTURE = "replay_fixture"
    LIVE_ENVIRONMENT = "live_environment"


class ValidationOutcome(StrEnum):
    PASSED = "passed"
    FAILED = "failed"


class SupportTarget(BaseModel):
    """One product-planned ruleset/revision/locale combination."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ruleset_id: RulesetId
    ruleset_revision_id: RulesetRevisionId
    locale_id: LocaleId


class ValidationRecord(BaseModel):
    """Minimal validation metadata without release approval semantics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ruleset_id: RulesetId
    ruleset_revision_id: RulesetRevisionId
    locale_id: LocaleId
    catalog_version: CatalogVersion
    validation_kind: ValidationKind
    outcome: ValidationOutcome
    validated_at: AwareDatetime
    evidence_references: tuple[str, ...] = Field(min_length=1)

    @field_validator("evidence_references")
    @classmethod
    def evidence_references_must_not_be_blank(
        cls,
        values: tuple[str, ...],
    ) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("validation evidence references cannot be blank")
        return values


class SupportRegistry(BaseModel):
    """Target declarations and individual validation records.

    Records never auto-promote a target to validated support.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    targets: tuple[SupportTarget, ...] = Field(default_factory=tuple)
    validation_records: tuple[ValidationRecord, ...] = Field(default_factory=tuple)

    def is_target(
        self,
        *,
        ruleset_id: RulesetId,
        ruleset_revision_id: RulesetRevisionId,
        locale_id: LocaleId,
    ) -> bool:
        """Return whether a combination is declared as product target support."""

        return any(
            target.ruleset_id == ruleset_id
            and target.ruleset_revision_id == ruleset_revision_id
            and target.locale_id == locale_id
            for target in self.targets
        )

    def records_for(
        self,
        *,
        ruleset_id: RulesetId,
        ruleset_revision_id: RulesetRevisionId,
        locale_id: LocaleId,
    ) -> tuple[ValidationRecord, ...]:
        """Return evidence records without deriving a validated-support claim."""

        return tuple(
            record
            for record in self.validation_records
            if record.ruleset_id == ruleset_id
            and record.ruleset_revision_id == ruleset_revision_id
            and record.locale_id == locale_id
        )
