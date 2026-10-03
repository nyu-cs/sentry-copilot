"""Declared private Additional Ban references with public catalog validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import cv2
import yaml

from sentry_copilot.capture.frame_source import ImageArray
from sentry_copilot.encounter.models import (
    ADDITIONAL_COVENANT_IDS,
    CovenantBanState,
    LocalizedText,
)
from sentry_copilot.image_io import load_bgr_image
from sentry_copilot.vision.additional_covenant_ban import (
    AdditionalCovenantReferencePack,
    AdditionalCovenantVisualReference,
)


@dataclass(frozen=True)
class AdditionalCovenantPresentationDefinition:
    covenant_id: str
    names: tuple[LocalizedText, ...]


@dataclass(frozen=True)
class AdditionalCovenantPresentationCatalog:
    definitions: tuple[AdditionalCovenantPresentationDefinition, ...]

    def __post_init__(self) -> None:
        if {item.covenant_id for item in self.definitions} != ADDITIONAL_COVENANT_IDS:
            raise ValueError("Additional presentation catalog must declare the supported pool")

    def by_id(self, covenant_id: str) -> AdditionalCovenantPresentationDefinition | None:
        return next((item for item in self.definitions if item.covenant_id == covenant_id), None)


def load_default_private_additional_covenant_ban_resources() -> tuple[
    AdditionalCovenantPresentationCatalog, AdditionalCovenantReferencePack
]:
    root = Path(__file__).resolve().parents[3]
    return load_additional_covenant_ban_resources(
        root / "data/catalogs/covenant_latter/covenant_catalog.yaml",
        root / "data/private/live_validation/ban_calibration/covenant_refs/manifest.json",
    )


def load_additional_covenant_ban_resources(
    catalog_path: Path, manifest_path: Path
) -> tuple[AdditionalCovenantPresentationCatalog, AdditionalCovenantReferencePack]:
    try:
        catalog = yaml.safe_load(catalog_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ValueError("Additional Covenant catalog YAML is invalid") from error
    if not isinstance(catalog, dict) or not isinstance(catalog.get("covenants"), list):
        raise ValueError("Additional Covenant catalog is invalid")
    covenant_records = tuple(
        cast(dict[str, Any], item) for item in catalog["covenants"] if isinstance(item, dict)
    )
    category = {item.get("covenant_id"): item.get("category") for item in covenant_records}
    additional_ids = {identity for identity, value in category.items() if value == "additional"}
    if additional_ids != ADDITIONAL_COVENANT_IDS:
        raise ValueError("Additional Covenant catalog IDs do not match the supported pool")
    try:
        records = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError("Additional Ban reference manifest is invalid") from error
    if not isinstance(records, list):
        raise ValueError("Additional Ban reference manifest must contain records")
    selected = [
        record
        for record in records
        if isinstance(record, dict) and record.get("group") == "additional"
    ]
    if (
        len(selected) != 15
        or {record.get("covenant_id") for record in selected} != ADDITIONAL_COVENANT_IDS
    ):
        raise ValueError(
            "Additional Ban reference manifest must cover every Additional Covenant once"
        )
    definitions = tuple(
        AdditionalCovenantPresentationDefinition(
            covenant_id=covenant_id,
            names=(
                LocalizedText(
                    locale_id="zh_CN",
                    text=_required_nonblank(record, "name_zh_CN"),
                ),
            ),
        )
        for covenant_id, record in sorted(
            (
                (str(record.get("covenant_id")), record)
                for record in covenant_records
                if record.get("category") == "additional"
            ),
            key=lambda item: item[0],
        )
    )
    references: list[AdditionalCovenantVisualReference] = []
    for record in selected:
        identity, state, raw_path = (
            record.get("covenant_id"),
            record.get("human_confirmed_ban_state"),
            record.get("source_frame"),
        )
        bounds = record.get("crop_bounds")
        if (
            not isinstance(identity, str)
            or not isinstance(state, str)
            or not isinstance(raw_path, str)
            or not isinstance(bounds, list)
            or len(bounds) != 4
        ):
            raise ValueError("Additional Ban reference record is missing required metadata")
        image = load_bgr_image(Path(raw_path))
        x, y, width, height = (int(value) for value in bounds)
        crop = image[y : y + height, x : x + width]
        if crop.shape != (height, width, 3):
            raise ValueError("Additional Ban reference crop is invalid")
        normalized = cast(
            ImageArray,
            cv2.getRectSubPix(crop, (112, 112), (width // 2, height // 2)),
        )
        references.append(
            AdditionalCovenantVisualReference(
                identity,
                CovenantBanState(state.lower()),
                normalized,
            )
        )
    return AdditionalCovenantPresentationCatalog(definitions), AdditionalCovenantReferencePack(
        tuple(references)
    )


def _required_nonblank(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Additional Covenant catalog record is missing required metadata")
    return value
