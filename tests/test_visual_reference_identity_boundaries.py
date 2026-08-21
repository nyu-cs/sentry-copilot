from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np
import yaml

from sentry_copilot.vision.visual_references import (
    VisualCatalogKind,
    load_visual_reference_catalog,
)


def _write_asset(path: Path, value: int) -> dict[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(path), np.full((4, 5, 3), value, dtype=np.uint8))
    return {
        "asset_id": path.stem.replace("_", "."),
        "asset_reference": path.relative_to(path.parents[1]).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "provenance": "synthetic-generated",
    }


def test_multiple_visual_assets_can_reference_one_strategy_without_occupancy_semantics(
    tmp_path: Path,
) -> None:
    first = _write_asset(tmp_path / "assets" / "asset.synthetic.canonical.png", 20)
    second = _write_asset(tmp_path / "assets" / "asset.synthetic.battle.png", 80)
    catalog_path = tmp_path / "catalog.yaml"
    catalog_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "kind": "strategy",
                "assets": [first, second],
                "strategy_references": [
                    {
                        "strategy_id": "strategy.synthetic.shared",
                        "asset_id": first["asset_id"],
                    },
                    {
                        "strategy_id": "strategy.synthetic.shared",
                        "asset_id": second["asset_id"],
                    },
                ],
                "avatar_references": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    catalog = load_visual_reference_catalog(catalog_path)

    assert catalog.kind is VisualCatalogKind.STRATEGY
    assert [reference.strategy_id for reference in catalog.references] == [
        "strategy.synthetic.shared",
        "strategy.synthetic.shared",
    ]
