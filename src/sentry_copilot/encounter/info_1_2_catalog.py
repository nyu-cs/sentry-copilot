"""Explicit private-reference loader for the bounded INFO 1/2 recognizer."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, cast

import yaml

from sentry_copilot.encounter.catalog import EncounterMapCatalog
from sentry_copilot.encounter.models import BossDefinition, EnemyCategoryDefinition, LocalizedText
from sentry_copilot.image_io import load_bgr_image, load_bgra_image
from sentry_copilot.vision.info_1_2 import (
    INFO_DIFFICULTY_IDS,
    KNOWN_DIFFICULTY_IDS,
    EnemyVisualReference,
    Info12ReferencePack,
    VisualReference,
    crop_info_difficulty_reference,
)


@dataclass(frozen=True)
class PrivateInfoDifficultyReferenceRegistration:
    """One declared private calibration asset; ``None`` reserves an uncalibrated identity."""

    difficulty_id: str
    relative_path: Path | None


# Frozen before independent PARTY1/PARTY2 holdout validation. Paths are relative
# to ``data/private`` and are explicit: this loader never discovers assets.
PRIVATE_INFO_DIFFICULTY_REFERENCE_REGISTRATIONS = (
    PrivateInfoDifficultyReferenceRegistration(
        "difficulty.covenant_latter.standard",
        Path("visual_catalogs/covenant_latter/calibration/solo_info_difficulty/adjacent/standard_solo/00-00-06-000_info-a.png"),
    ),
    PrivateInfoDifficultyReferenceRegistration(
        "difficulty.covenant_latter.standard",
        Path("visual_catalogs/covenant_latter/calibration/solo_info_difficulty/adjacent/standard_coop4/00-00-28-300_info-a.png"),
    ),
    PrivateInfoDifficultyReferenceRegistration(
        "difficulty.covenant_latter.adversity",
        Path("visual_catalogs/covenant_latter/calibration/solo_info_difficulty/adjacent/adversity_solo/00-00-05-300_info-a.png"),
    ),
    PrivateInfoDifficultyReferenceRegistration(
        "difficulty.covenant_latter.deadland",
        Path("visual_catalogs/covenant_latter/calibration/solo_info_difficulty/adjacent/deadland_solo/00-00-08-100_info-a.png"),
    ),
    PrivateInfoDifficultyReferenceRegistration(
        "difficulty.covenant_latter.deadland",
        Path("live_validation/info_1_2_deadland_variant_calibration/frames/deadland_coop3_transition/00-00-07-700_fade-b.png"),
    ),
    PrivateInfoDifficultyReferenceRegistration(
        "difficulty.covenant_latter.ultimate",
        Path("live_validation/ac4_ultimate_calibration/ac4_ultimate_solo_001_2026-09-04_16-12-33/frames/info_1_2/00-00-05-000_info_05_0.png"),
    ),
)


def calibrated_info_difficulty_reference_registrations(
) -> tuple[PrivateInfoDifficultyReferenceRegistration, ...]:
    """Return only explicitly declared production-calibrated reference registrations."""

    registrations = tuple(
        item for item in PRIVATE_INFO_DIFFICULTY_REFERENCE_REGISTRATIONS if item.relative_path
    )
    if {item.difficulty_id for item in registrations} != set(INFO_DIFFICULTY_IDS):
        raise ValueError("declared INFO Difficulty references do not match calibrated identities")
    all_registered_ids = {
        item.difficulty_id for item in PRIVATE_INFO_DIFFICULTY_REFERENCE_REGISTRATIONS
    }
    if all_registered_ids != set(KNOWN_DIFFICULTY_IDS):
        raise ValueError("declared INFO Difficulty registrations do not match known identities")
    return registrations


def load_info_1_2_resources(
    boss_catalog: Path,
    enemy_catalog: Path,
    anchor: Path,
    boss_root: Path,
    enemy_root: Path,
    base: EncounterMapCatalog,
) -> tuple[EncounterMapCatalog, Info12ReferencePack]:
    try:
        bosses_raw = _records(_mapping(boss_catalog), "ordinary_boss_pool")
        enemies_raw = _records(_mapping(enemy_catalog), "enemy_categories")
        bosses = tuple(_boss_definition(item) for item in bosses_raw)
        enemies = tuple(_enemy_definition(item) for item in enemies_raw)
        if any(base.difficulty_by_id(identity_id) is None for identity_id in INFO_DIFFICULTY_IDS):
            raise ValueError("INFO difficulty reference IDs are absent from the encounter catalog")
        pack = Info12ReferencePack(
            load_bgr_image(anchor),
            tuple(_reference(item, boss_root, "boss_id") for item in bosses_raw),
            tuple(_enemy_reference(item, enemy_root) for item in enemies_raw),
            _load_declared_difficulty_references(Path("data/private")),
        )
        return replace(base, bosses=bosses, enemy_categories=enemies), pack
    except KeyError as error:
        raise ValueError("INFO catalog is missing a required record field") from error


def _load_declared_difficulty_references(calibration_root: Path) -> tuple[VisualReference, ...]:
    """Load only currently calibrated, explicitly named private assets."""

    return tuple(
        VisualReference(
            item.difficulty_id,
            crop_info_difficulty_reference(load_bgr_image(calibration_root / item.relative_path)),
        )
        for item in calibrated_info_difficulty_reference_registrations()
        if item.relative_path is not None
    )


def load_default_private_info_1_2_resources(
    base: EncounterMapCatalog,
) -> tuple[EncounterMapCatalog, Info12ReferencePack]:
    """Load only declared private calibration assets; never discover or scan directories."""
    root = Path("data")
    catalog, pack = load_info_1_2_resources(
        root / "catalogs/covenant_latter/boss_catalog_covenant_latter_draft.yaml",
        root / "catalogs/covenant_latter/enemy_category_catalog_covenant_latter_draft.yaml",
        root
        / "private/visual_catalogs/covenant_latter/calibration/info_1_2/roi_crops"
        / "anchor_genuine_info_1_2.png",
        root / "private/visual_catalogs/covenant_latter/boss",
        root / "private/visual_catalogs/covenant_latter/enemy_category",
        base,
    )
    return catalog, pack


def _mapping(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ValueError("INFO catalog YAML is invalid") from error
    if not isinstance(value, dict):
        raise ValueError("INFO catalog must contain a mapping")
    return cast(dict[str, Any], value)


def _records(mapping: dict[str, Any], key: str) -> tuple[dict[str, Any], ...]:
    value = mapping.get(key)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"catalog {key} must be a list of records")
    return tuple(cast(dict[str, Any], item) for item in value)


def _names(item: dict[str, Any]) -> tuple[LocalizedText, ...]:
    value = item.get("names")
    if not isinstance(value, dict):
        raise ValueError("catalog identity must contain names")
    return tuple(
        LocalizedText(locale_id=str(locale), text=str(text)) for locale, text in value.items()
    )


def _boss_definition(item: dict[str, Any]) -> BossDefinition:
    return BossDefinition(boss_id=str(item["boss_id"]), names=_names(item))


def _enemy_definition(item: dict[str, Any]) -> EnemyCategoryDefinition:
    return EnemyCategoryDefinition(
        enemy_category_id=str(item["enemy_category_id"]), names=_names(item)
    )


def _reference(item: dict[str, Any], root: Path, key: str) -> VisualReference:
    if not isinstance(item.get("visual_reference"), dict):
        raise ValueError("catalog identity must contain visual_reference")
    filename = str(item["visual_reference"]["local_filename"])
    path = root / filename
    if not path.is_file():
        path = path.with_suffix(".webp")
    return VisualReference(str(item[key]), load_bgr_image(path))


def _enemy_reference(item: dict[str, Any], root: Path) -> EnemyVisualReference:
    if not isinstance(item.get("visual_reference"), dict):
        raise ValueError("catalog identity must contain visual_reference")
    path = root / str(item["visual_reference"]["local_filename"])
    return EnemyVisualReference(str(item["enemy_category_id"]), load_bgra_image(path))
