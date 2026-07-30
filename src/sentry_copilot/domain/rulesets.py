from __future__ import annotations

from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from .evidence import EvidenceRecord
from .identifiers import (
    CatalogVersion,
    LocaleId,
    RulesetId,
    RulesetRevisionId,
)


class RevisionSelectionMethod(StrEnum):
    """How the current session revision was selected."""

    MANUAL = "manual"
    AUTO_DETECTED = "auto_detected"
    IMPORTED_FROM_REPLAY_METADATA = "imported_from_replay_metadata"
    UNKNOWN = "unknown"


class RevisionSelectionRecord(BaseModel):
    """One replaced ruleset-revision selection in the session audit history."""

    model_config = ConfigDict(frozen=True)

    ruleset_revision_id: RulesetRevisionId
    catalog_version: CatalogVersion
    selection_method: RevisionSelectionMethod
    selected_at: AwareDatetime
    replaced_at: AwareDatetime
    context_generation: int = Field(ge=1)
    evidence: tuple[EvidenceRecord, ...] = Field(default_factory=tuple)
    reason: str | None = None

    @model_validator(mode="after")
    def selection_is_internally_consistent(self) -> RevisionSelectionRecord:
        _require_revision_selection_fields(
            self.ruleset_revision_id,
            self.catalog_version,
            self.selection_method,
            self.context_generation,
        )
        if self.replaced_at < self.selected_at:
            raise ValueError("replaced_at cannot precede selected_at")
        if self.reason is not None and not self.reason.strip():
            raise ValueError("revision selection reason cannot be blank")
        return self


class RulesetDependencyStamp(BaseModel):
    """Identity of the ruleset context used by revision-dependent derived data."""

    model_config = ConfigDict(frozen=True)

    ruleset_id: RulesetId
    ruleset_revision_id: RulesetRevisionId
    locale_id: LocaleId
    catalog_version: CatalogVersion
    context_generation: int = Field(ge=1)


class SessionRulesetContext(BaseModel):
    """Authoritative ruleset, revision, locale, and catalog selection for one session."""

    model_config = ConfigDict(frozen=True)

    ruleset_id: RulesetId
    ruleset_revision_id: RulesetRevisionId | None = None
    locale_id: LocaleId
    catalog_version: CatalogVersion | None = None
    selection_method: RevisionSelectionMethod = RevisionSelectionMethod.UNKNOWN
    selected_at: AwareDatetime
    selection_evidence: tuple[EvidenceRecord, ...] = Field(default_factory=tuple)
    revision_history: tuple[RevisionSelectionRecord, ...] = Field(default_factory=tuple)
    context_generation: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def current_selection_is_internally_consistent(self) -> SessionRulesetContext:
        _require_revision_selection_fields(
            self.ruleset_revision_id,
            self.catalog_version,
            self.selection_method,
            self.context_generation,
        )
        history_generations = tuple(
            record.context_generation for record in self.revision_history
        )
        expected_generations = tuple(range(1, self.context_generation))
        if history_generations != expected_generations:
            raise ValueError(
                "revision history must contain each replaced context generation in order"
            )
        return self

    @property
    def dependency_stamp(self) -> RulesetDependencyStamp | None:
        """Return the current dependency identity, or None while revision is unknown."""

        if self.ruleset_revision_id is None or self.catalog_version is None:
            return None
        return RulesetDependencyStamp(
            ruleset_id=self.ruleset_id,
            ruleset_revision_id=self.ruleset_revision_id,
            locale_id=self.locale_id,
            catalog_version=self.catalog_version,
            context_generation=self.context_generation,
        )


def _require_revision_selection_fields(
    ruleset_revision_id: RulesetRevisionId | None,
    catalog_version: CatalogVersion | None,
    selection_method: RevisionSelectionMethod,
    context_generation: int,
) -> None:
    if ruleset_revision_id is None:
        if catalog_version is not None:
            raise ValueError("unknown revision cannot have a catalog_version")
        if selection_method != RevisionSelectionMethod.UNKNOWN:
            raise ValueError("unknown revision requires unknown selection method")
        if context_generation != 0:
            raise ValueError("an unselected revision context must remain at generation zero")
        return
    if catalog_version is None:
        raise ValueError("selected revision requires catalog_version")
    if selection_method == RevisionSelectionMethod.UNKNOWN:
        raise ValueError("selected revision requires a known selection method")
    if context_generation < 1:
        raise ValueError("selected revision requires a positive context generation")
