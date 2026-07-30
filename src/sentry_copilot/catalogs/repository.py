from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from sentry_copilot.domain.identifiers import (
    CatalogVersion,
    LocaleId,
    RulesetId,
    RulesetRevisionId,
    StrategyId,
)
from sentry_copilot.domain.strategy import (
    LocaleStrategyResource,
    ProtocolRuleset,
    RulesetRevision,
    RulesetStrategyProfile,
    StrategyAvailability,
    StrategyCatalog,
)
from sentry_copilot.domain.support import SupportRegistry

from .validation import validate_catalog, validate_support_registry


class CatalogLoadError(ValueError):
    """Raised when catalog YAML cannot be parsed into a valid catalog."""


class CatalogLookupError(LookupError):
    """Raised when an exact revision-aware catalog lookup has no result."""


@dataclass(frozen=True)
class LoadedStrategyCatalog:
    catalog: StrategyCatalog
    asset_root: Path


class StrategyCatalogRepository:
    """Validated read-only strategy catalogs indexed by catalog version."""

    def __init__(self, catalogs: tuple[LoadedStrategyCatalog, ...]) -> None:
        if not catalogs:
            raise CatalogLoadError("strategy catalog repository cannot be empty")
        versions = [entry.catalog.catalog_version for entry in catalogs]
        if len(versions) != len(set(versions)):
            raise CatalogLoadError("catalog_version values must be repository-unique")
        for entry in catalogs:
            validate_catalog(entry.catalog, asset_root=entry.asset_root)
        self._catalogs = catalogs

    @classmethod
    def from_directory(cls, directory: str | Path) -> StrategyCatalogRepository:
        root = Path(directory)
        catalog_paths = sorted(root.glob("*/catalog.yaml"))
        if not catalog_paths:
            raise CatalogLoadError(f"no strategy catalogs found under {root}")
        return cls(tuple(load_catalog(path) for path in catalog_paths))

    def list_catalog_versions(self) -> tuple[CatalogVersion, ...]:
        return tuple(
            sorted(entry.catalog.catalog_version for entry in self._catalogs)
        )

    def catalog(self, catalog_version: CatalogVersion) -> StrategyCatalog:
        for entry in self._catalogs:
            if entry.catalog.catalog_version == catalog_version:
                return entry.catalog
        raise CatalogLookupError(f"unknown catalog_version: {catalog_version}")

    def get_ruleset(
        self,
        *,
        catalog_version: CatalogVersion,
        ruleset_id: RulesetId,
    ) -> ProtocolRuleset:
        catalog = self.catalog(catalog_version)
        for ruleset in catalog.rulesets:
            if ruleset.ruleset_id == ruleset_id:
                return ruleset
        raise CatalogLookupError(
            "ruleset not found for exact catalog/ruleset key"
        )

    def get_revision(
        self,
        *,
        catalog_version: CatalogVersion,
        ruleset_revision_id: RulesetRevisionId,
    ) -> RulesetRevision:
        catalog = self.catalog(catalog_version)
        for revision in catalog.revisions:
            if revision.ruleset_revision_id == ruleset_revision_id:
                return revision
        raise CatalogLookupError(
            "revision not found for exact catalog/revision key"
        )

    def get_profile(
        self,
        *,
        catalog_version: CatalogVersion,
        ruleset_revision_id: RulesetRevisionId,
        strategy_id: StrategyId,
    ) -> RulesetStrategyProfile:
        catalog = self.catalog(catalog_version)
        for profile in catalog.profiles:
            if (
                profile.ruleset_revision_id == ruleset_revision_id
                and profile.strategy_id == strategy_id
            ):
                return profile
        raise CatalogLookupError(
            "strategy profile not found for exact catalog/revision/strategy key"
        )

    def get_locale_resource(
        self,
        *,
        catalog_version: CatalogVersion,
        ruleset_revision_id: RulesetRevisionId,
        strategy_id: StrategyId,
        locale_id: LocaleId,
    ) -> LocaleStrategyResource:
        catalog = self.catalog(catalog_version)
        for resource in catalog.locale_resources:
            if (
                resource.ruleset_revision_id == ruleset_revision_id
                and resource.strategy_id == strategy_id
                and resource.locale_id == locale_id
            ):
                return resource
        raise CatalogLookupError(
            "locale resource not found for exact catalog/revision/strategy/locale key"
        )

    def available_strategy_ids(
        self,
        *,
        catalog_version: CatalogVersion,
        ruleset_revision_id: RulesetRevisionId,
    ) -> frozenset[StrategyId]:
        catalog = self.catalog(catalog_version)
        return frozenset(
            profile.strategy_id
            for profile in catalog.profiles
            if profile.ruleset_revision_id == ruleset_revision_id
            and profile.availability == StrategyAvailability.AVAILABLE
        )


def load_catalog(path: str | Path) -> LoadedStrategyCatalog:
    catalog_path = Path(path)
    raw = _load_yaml_mapping(catalog_path)
    try:
        catalog = StrategyCatalog.model_validate(raw)
    except ValidationError as exc:
        raise CatalogLoadError(f"invalid strategy catalog: {catalog_path}") from exc
    validate_catalog(catalog, asset_root=catalog_path.parent)
    return LoadedStrategyCatalog(catalog=catalog, asset_root=catalog_path.parent)


def load_support_registry(path: str | Path) -> SupportRegistry:
    registry_path = Path(path)
    raw = _load_yaml_mapping(registry_path)
    try:
        registry = SupportRegistry.model_validate(raw)
    except ValidationError as exc:
        raise CatalogLoadError(f"invalid support registry: {registry_path}") from exc
    validate_support_registry(registry)
    return registry


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            raw: object = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise CatalogLoadError(f"unable to read YAML: {path}") from exc
    if not isinstance(raw, dict) or any(not isinstance(key, str) for key in raw):
        raise CatalogLoadError(f"YAML root must be a string-keyed mapping: {path}")
    return raw
