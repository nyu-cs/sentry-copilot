from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .identifiers import (
    CatalogVersion,
    LocaleId,
    RulesetId,
    RulesetRevisionId,
    StrategyId,
)


class StrategyAvailability(StrEnum):
    """Whether a strategy profile is selectable in one ruleset revision."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


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

    @field_validator("icon_visual_key", "icon_asset_reference")
    @classmethod
    def icon_values_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("strategy icon values cannot be blank")
        return value


class LocaleStrategyResource(BaseModel):
    """Revision- and locale-specific human-readable strategy resources."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ruleset_revision_id: RulesetRevisionId
    strategy_id: StrategyId
    locale_id: LocaleId
    name: str
    description: str
    ocr_aliases: frozenset[str] = Field(default_factory=frozenset)
    visible_text_variants: frozenset[str] = Field(default_factory=frozenset)

    @field_validator("name", "description")
    @classmethod
    def localized_text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("localized strategy text cannot be blank")
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
    rulesets: tuple[ProtocolRuleset, ...] = Field(min_length=1)
    revisions: tuple[RulesetRevision, ...] = Field(min_length=1)
    strategy_identities: tuple[StrategyIdentity, ...] = Field(min_length=1)
    profiles: tuple[RulesetStrategyProfile, ...] = Field(min_length=1)
    locale_resources: tuple[LocaleStrategyResource, ...] = Field(min_length=1)
