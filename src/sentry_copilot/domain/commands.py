from __future__ import annotations

from typing import Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)

from .evidence import EvidenceRecord
from .identifiers import (
    CatalogVersion,
    LocaleId,
    RulesetId,
    RulesetRevisionId,
)
from .rulesets import RevisionSelectionMethod


class RulesetContextCommand(BaseModel):
    """Shared immutable input for explicit ruleset-context operations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: str = Field(min_length=1)
    ruleset_id: RulesetId
    ruleset_revision_id: RulesetRevisionId
    locale_id: LocaleId
    catalog_version: CatalogVersion
    selected_at: AwareDatetime
    selection_evidence: tuple[EvidenceRecord, ...] = Field(default_factory=tuple)
    reason: str | None = None

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("ruleset context command reason cannot be blank")
        return value


class SelectSessionRulesetContext(RulesetContextCommand):
    """Select a concrete revision manually or from explicit replay metadata."""

    selection_method: RevisionSelectionMethod

    @field_validator("selection_method")
    @classmethod
    def method_must_be_supported(
        cls,
        value: RevisionSelectionMethod,
    ) -> RevisionSelectionMethod:
        if value not in (
            RevisionSelectionMethod.MANUAL,
            RevisionSelectionMethod.IMPORTED_FROM_REPLAY_METADATA,
        ):
            raise ValueError(
                "initial selection must be manual or imported from replay metadata"
            )
        return value


class CorrectSessionRulesetRevision(RulesetContextCommand):
    """Explicitly correct the current revision or catalog version."""

    selection_method: Literal[RevisionSelectionMethod.MANUAL] = (
        RevisionSelectionMethod.MANUAL
    )
