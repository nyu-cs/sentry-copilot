"""Reusable operator-portrait source metadata, independent from seasonal gameplay catalogs."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml


@dataclass(frozen=True)
class OperatorPortraitSource:
    """One provider-backed Elite-0 portrait identity with no ruleset gameplay metadata."""

    portrait_key: str
    name_zh_CN: str
    provider: str
    file_title: str
    source_page: str
    base_variant: str
    explicit_override_note: str | None = None


@dataclass(frozen=True)
class OperatorPortraitSourceCatalog:
    """Immutable source manifest with deterministic private cache naming."""

    sources: tuple[OperatorPortraitSource, ...]

    def __post_init__(self) -> None:
        portrait_keys = tuple(item.portrait_key for item in self.sources)
        names = tuple(item.name_zh_CN for item in self.sources)
        if len(portrait_keys) != len(set(portrait_keys)):
            raise ValueError("operator portrait sources must have unique portrait keys")
        if len(names) != len(set(names)):
            raise ValueError("operator portrait sources must have unique Chinese names")

    def by_name_zh_CN(self, name_zh_CN: str) -> OperatorPortraitSource | None:
        return next((item for item in self.sources if item.name_zh_CN == name_zh_CN), None)

    def by_portrait_key(self, portrait_key: str) -> OperatorPortraitSource | None:
        return next((item for item in self.sources if item.portrait_key == portrait_key), None)

    @staticmethod
    def private_cache_path(cache_root: Path, portrait_key: str) -> Path:
        """Map one reusable source identity to a Windows-safe local PNG cache filename."""

        digest = hashlib.sha256(portrait_key.encode("utf-8")).hexdigest()
        return cache_root / f"{digest}.png"


def default_operator_portrait_source_manifest_path() -> Path:
    """Return the explicitly declared public source manifest; never scan a directory."""

    return (
        Path(__file__).resolve().parents[3]
        / "data"
        / "catalogs"
        / "operator_portrait_sources.yaml"
    )


def load_operator_portrait_source_catalog(path: Path) -> OperatorPortraitSourceCatalog:
    """Load one public source-only manifest without downloading assets."""

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ValueError("operator portrait source manifest YAML is invalid") from error
    if not isinstance(raw, dict):
        raise ValueError("operator portrait source manifest must contain a mapping")
    records = raw.get("portrait_sources")
    if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
        raise ValueError("operator portrait source manifest is missing source records")
    return OperatorPortraitSourceCatalog(
        tuple(_source_from_record(cast(dict[str, Any], item)) for item in records)
    )


def load_default_operator_portrait_source_catalog() -> OperatorPortraitSourceCatalog:
    """Load the one declared source manifest; cache/network access remains caller-owned."""

    return load_operator_portrait_source_catalog(default_operator_portrait_source_manifest_path())


def default_operator_portrait_private_cache_root() -> Path:
    """Return the one caller-owned private cache root; never scan it for identities."""

    return (
        Path(__file__).resolve().parents[3]
        / "data"
        / "private"
        / "assets"
        / "operator_portraits"
        / "prts"
    )


def _source_from_record(record: dict[str, Any]) -> OperatorPortraitSource:
    forbidden = {"tier", "covenant_ids", "memberships", "recruitment_route", "ban_state"}
    if forbidden.intersection(record):
        raise ValueError("operator portrait source manifest must not contain gameplay metadata")
    name = _required_text(record, "name_zh_CN")
    portrait_key = _required_text(record, "portrait_key")
    if portrait_key != f"prts:{name}":
        raise ValueError("operator portrait key must use the reusable PRTS name identity")
    if _required_text(record, "provider") != "PRTS":
        raise ValueError("operator portrait source provider must be PRTS")
    if _required_text(record, "base_variant") != "elite_0":
        raise ValueError("operator portrait source must use the Elite-0 base variant")
    override = record.get("explicit_override_note")
    if override is not None and (not isinstance(override, str) or not override.strip()):
        raise ValueError("operator portrait override note must be nonblank when present")
    return OperatorPortraitSource(
        portrait_key=portrait_key,
        name_zh_CN=name,
        provider="PRTS",
        file_title=_required_text(record, "file_title"),
        source_page=_required_text(record, "source_page"),
        base_variant="elite_0",
        explicit_override_note=override,
    )


def _required_text(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("operator portrait source record is missing required metadata")
    return value
