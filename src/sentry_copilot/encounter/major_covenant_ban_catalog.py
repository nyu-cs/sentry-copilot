"""Declared Major/Core Ban references and presentation metadata; never directory-discovered."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml

from sentry_copilot.encounter.models import MAJOR_COVENANT_IDS, CovenantBanState, LocalizedText
from sentry_copilot.image_io import load_bgr_image
from sentry_copilot.vision.major_covenant_ban import (
    MajorCovenantReferencePack,
    MajorCovenantVisualReference,
)


@dataclass(frozen=True)
class MajorCovenantPresentationDefinition:
    covenant_id: str
    names: tuple[LocalizedText, ...]


@dataclass(frozen=True)
class MajorCovenantPresentationCatalog:
    definitions: tuple[MajorCovenantPresentationDefinition, ...]

    def __post_init__(self) -> None:
        if {item.covenant_id for item in self.definitions} != MAJOR_COVENANT_IDS:
            raise ValueError(
                "Major presentation catalog must declare every supported Major/Core ID"
            )

    def by_id(self, covenant_id: str) -> MajorCovenantPresentationDefinition | None:
        return next((item for item in self.definitions if item.covenant_id == covenant_id), None)


def load_major_covenant_ban_resources(
    covenant_catalog_path: Path,
    reference_manifest_path: Path,
) -> tuple[MajorCovenantPresentationCatalog, MajorCovenantReferencePack]:
    """Load one explicit 40-exemplar private pack and its public Core Covenant metadata."""

    catalog = _load_yaml_mapping(covenant_catalog_path)
    definitions = _major_definitions(catalog)
    manifest = _load_json_mapping(reference_manifest_path)
    records = manifest.get("records")
    if not isinstance(records, list) or len(records) != 40:
        raise ValueError(
            "Major Ban reference manifest must contain exactly forty retained exemplars"
        )
    references = tuple(
        _reference_from_record(cast(dict[str, Any], record), reference_manifest_path.parent)
        for record in records
        if isinstance(record, dict)
    )
    if len(references) != 40 or {item.covenant_id for item in references} != MAJOR_COVENANT_IDS:
        raise ValueError("Major Ban reference manifest must cover each Major/Core Covenant")
    return MajorCovenantPresentationCatalog(definitions), MajorCovenantReferencePack(references)


def load_default_private_major_covenant_ban_resources() -> tuple[
    MajorCovenantPresentationCatalog, MajorCovenantReferencePack
]:
    """Load only the declared local Major reference pack; do not discover private assets."""

    repository_root = Path(__file__).resolve().parents[3]
    presentation, initial_references = load_major_covenant_ban_resources(
        repository_root / "data/catalogs/covenant_latter/covenant_catalog.yaml",
        repository_root
        / "data/private/live_validation/ban_calibration/major_initial_info"
        / "major_refs/manifest.json",
    )
    returned_references = _load_returned_info_references(
        repository_root
        / "data/private/live_validation/ban_calibration/major_returned_info"
        / "major_refs/manifest.json"
    )
    return presentation, MajorCovenantReferencePack(
        initial_references.references,
        returned_references,
    )


def _load_returned_info_references(
    reference_manifest_path: Path,
) -> tuple[MajorCovenantVisualReference, ...]:
    """Load the explicit two-session returned-INFO Major exemplar pack without discovery."""

    manifest = _load_json_mapping(reference_manifest_path)
    records = manifest.get("records")
    if not isinstance(records, list) or len(records) != 16:
        raise ValueError("Returned Major reference manifest must contain exactly sixteen exemplars")
    references = tuple(
        _reference_from_record(cast(dict[str, Any], record), reference_manifest_path.parent)
        for record in records
        if isinstance(record, dict)
    )
    counts = Counter(item.covenant_id for item in references)
    if len(references) != 16 or set(counts) != MAJOR_COVENANT_IDS or set(counts.values()) != {2}:
        raise ValueError(
            "Returned Major reference manifest must retain exactly two exemplars per Major/Core ID"
        )
    return references


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ValueError("Major Covenant catalog YAML is invalid") from error
    if not isinstance(value, dict):
        raise ValueError("Major Covenant catalog must contain a mapping")
    return cast(dict[str, Any], value)


def _load_json_mapping(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError("Major Ban reference manifest is invalid") from error
    if not isinstance(value, dict):
        raise ValueError("Major Ban reference manifest must contain a mapping")
    return cast(dict[str, Any], value)


def _major_definitions(
    catalog: dict[str, Any],
) -> tuple[MajorCovenantPresentationDefinition, ...]:
    records = catalog.get("covenants")
    if not isinstance(records, list):
        raise ValueError("Major Covenant catalog is missing covenant records")
    core_records = {
        str(item.get("covenant_id")): item
        for item in records
        if isinstance(item, dict) and item.get("category") == "core"
    }
    if set(core_records) != MAJOR_COVENANT_IDS:
        raise ValueError("Major Covenant catalog Core IDs do not match the supported Major pool")
    return tuple(
        MajorCovenantPresentationDefinition(
            covenant_id=covenant_id,
            names=(
                LocalizedText(
                    locale_id="zh_CN",
                    text=_required_nonblank_text(core_records[covenant_id], "name_zh_CN"),
                ),
            ),
        )
        for covenant_id in sorted(MAJOR_COVENANT_IDS)
    )


def _reference_from_record(
    record: dict[str, Any], reference_root: Path
) -> MajorCovenantVisualReference:
    covenant_id = _required_nonblank_text(record, "covenant_id")
    state_value = _required_nonblank_text(record, "human_confirmed_ban_state")
    raw_crop = _required_nonblank_text(record, "raw_crop_path")
    path = Path(raw_crop)
    if not path.is_file():
        path = reference_root / "raw_recentered" / _path_basename(raw_crop)
    return MajorCovenantVisualReference(
        covenant_id=covenant_id,
        state=CovenantBanState(state_value.lower()),
        image=load_bgr_image(path),
    )


def _required_nonblank_text(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Major Ban reference record is missing required metadata")
    return value


def _path_basename(value: str) -> str:
    parts = tuple(part for part in value.replace("\\", "/").split("/") if part)
    if not parts:
        raise ValueError("Major Ban reference asset path is invalid")
    return parts[-1]
