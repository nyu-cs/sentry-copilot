from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .identifiers import (
    CatalogVersion,
    LocaleId,
    RulesetId,
    RulesetRevisionId,
    StrategyId,
    StrategyPhaseId,
)


class StrategyAvailability(StrEnum):
    """Whether a strategy is globally selectable in one catalog context."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class StrategyMetadataProvenance(StrEnum):
    """Small source-level distinction for bootstrapped catalog facts."""

    LIVE_CONFIRMED = "live_confirmed"
    OFFICIAL_NOTICE = "official_notice"
    EXTERNAL_REFERENCE = "external_reference"


class IconAssetMaterialization(StrEnum):
    """Whether revision profile paths are bundled or supplied privately by the caller."""

    PACKAGED = "packaged"
    PRIVATE_LOCAL = "private_local"


class ProtocolRuleset(BaseModel):
    """One language-independent gameplay ruleset."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ruleset_id: RulesetId
    revision_ids: frozenset[RulesetRevisionId] = Field(min_length=1)
    supported_locales: frozenset[LocaleId] = Field(min_length=1)


class RulesetRevision(BaseModel):
    """One immutable catalog state within a protocol ruleset."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ruleset_revision_id: RulesetRevisionId
    ruleset_id: RulesetId
    revision_order: int = Field(ge=0)


class StrategyIdentity(BaseModel):
    """Stable normalized strategy identity with no icon authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_id: StrategyId


class RulesetStrategyProfile(BaseModel):
    """Revision-specific strategy values and authoritative icon mapping."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ruleset_revision_id: RulesetRevisionId
    strategy_id: StrategyId
    availability: StrategyAvailability
    initial_hp: int = Field(gt=0)
    icon_visual_key: str
    icon_asset_reference: str
    initial_hp_provenance: StrategyMetadataProvenance | None = None
    initial_hp_source_reference: str | None = None

    @field_validator("initial_hp_source_reference")
    @classmethod
    def initial_hp_source_reference_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("initial_hp_source_reference cannot be blank when supplied")
        return value

    @field_validator("icon_visual_key", "icon_asset_reference")
    @classmethod
    def icon_values_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("strategy icon values cannot be blank")
        return value


class StrategyPhaseAvailability(BaseModel):
    """One global phase availability fact, distinct from per-player unlocks and profiles."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    phase_id: StrategyPhaseId
    ruleset_revision_id: RulesetRevisionId
    strategy_id: StrategyId
    availability: StrategyAvailability
    provenance: StrategyMetadataProvenance
    source_reference: str

    @field_validator("source_reference")
    @classmethod
    def source_reference_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source_reference cannot be blank")
        return value


class LocaleStrategyResource(BaseModel):
    """Revision- and locale-specific human-readable strategy resources."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ruleset_revision_id: RulesetRevisionId
    strategy_id: StrategyId
    locale_id: LocaleId
    name: str
    description: str
    initiator_display_name: str | None = None
    ocr_aliases: frozenset[str] = Field(default_factory=frozenset)
    visible_text_variants: frozenset[str] = Field(default_factory=frozenset)

    @field_validator("name", "description")
    @classmethod
    def localized_text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("localized strategy text cannot be blank")
        return value

    @field_validator("initiator_display_name")
    @classmethod
    def initiator_display_name_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("initiator_display_name cannot be blank when supplied")
        return value

    @field_validator("ocr_aliases", "visible_text_variants")
    @classmethod
    def text_sets_must_not_contain_blanks(
        cls,
        values: frozenset[str],
    ) -> frozenset[str]:
        if any(not value.strip() for value in values):
            raise ValueError("localized strategy text sets cannot contain blank values")
        return values


class StrategyCatalog(BaseModel):
    """Immutable catalog aggregate loaded and cross-validated by the repository."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    catalog_version: CatalogVersion
    is_synthetic: bool
    icon_asset_materialization: IconAssetMaterialization = IconAssetMaterialization.PACKAGED
    rulesets: tuple[ProtocolRuleset, ...] = Field(min_length=1)
    revisions: tuple[RulesetRevision, ...] = Field(min_length=1)
    strategy_identities: tuple[StrategyIdentity, ...] = Field(min_length=1)
    profiles: tuple[RulesetStrategyProfile, ...] = Field(min_length=1)
    locale_resources: tuple[LocaleStrategyResource, ...] = Field(min_length=1)
    phase_availabilities: tuple[StrategyPhaseAvailability, ...] = Field(default_factory=tuple)
