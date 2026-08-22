from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml

from sentry_copilot.image_io import load_bgr_image, write_bgr_png
from sentry_copilot.vision.strategy_selection_probe import (
    JP_MUMU_1920X1080_PROFILE_ID,
    StrategySelectionProbeStatus,
    probe_strategy_selection_image,
    write_strategy_selection_probe_result,
)
from sentry_copilot.vision.visual_references import load_visual_reference_catalog


def _catalog(tmp_path: Path, image: np.ndarray) -> Path:
    asset = tmp_path / "asset.png"
    write_bgr_png(asset, image)
    path = tmp_path / "catalog.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "kind": "strategy",
                "assets": [
                    {
                        "asset_id": "asset.synthetic.portrait",
                        "asset_reference": "asset.png",
                        "sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
                    }
                ],
                "strategy_references": [
                    {
                        "strategy_id": "strategy.synthetic.portrait",
                        "asset_id": "asset.synthetic.portrait",
                        "reference_kind": "selection_render",
                    }
                ],
                "avatar_references": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def _image(
    tmp_path: Path,
    portrait: np.ndarray,
    *,
    blank_row: int | None = None,
    width: int = 1920,
    height: int = 1080,
) -> Path:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    for row, y in enumerate((304, 452, 600, 748), start=1):
        if row != blank_row and y + 34 + 70 <= height and 593 + 24 + 88 <= width:
            image[y + 34 : y + 104, 617:705] = portrait
    path = tmp_path / "frame.png"
    write_bgr_png(path, image)
    return path


def _portrait() -> np.ndarray:
    image = np.zeros((70, 88, 3), dtype=np.uint8)
    cv2.circle(image, (25, 27), 17, (200, 50, 240), 2)
    cv2.line(image, (5, 61), (81, 8), (20, 220, 120), 2)
    cv2.putText(image, "A", (48, 56), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    return image


def test_probe_uses_exact_geometry_and_preserves_row_order(tmp_path: Path) -> None:
    portrait = _portrait()
    result = probe_strategy_selection_image(
        _image(tmp_path, portrait), load_visual_reference_catalog(_catalog(tmp_path, portrait))
    )
    assert result.geometry_profile_id == JP_MUMU_1920X1080_PROFILE_ID
    assert [row.selection_row for row in result.rows] == [1, 2, 3, 4]
    assert [row.row_roi.y for row in result.rows] == [304, 452, 600, 748]
    assert all(
        (row.portrait_roi.x, row.portrait_roi.width, row.portrait_roi.height) == (617, 88, 70)
        for row in result.rows
    )
    assert all(row.status is StrategySelectionProbeStatus.MATCHED_STRATEGY for row in result.rows)
    assert all(row.strategy_id == "strategy.synthetic.portrait" for row in result.rows)


def test_probe_rejects_non_baseline_dimensions(tmp_path: Path) -> None:
    portrait = _portrait()
    with pytest.raises(ValueError, match="1920x1080"):
        probe_strategy_selection_image(
            _image(tmp_path, portrait, width=1919),
            load_visual_reference_catalog(_catalog(tmp_path, portrait)),
        )


def test_blank_row_remains_vision_only_no_candidate_and_json_is_deterministic(
    tmp_path: Path,
) -> None:
    portrait = _portrait()
    result = probe_strategy_selection_image(
        _image(tmp_path, portrait, blank_row=2),
        load_visual_reference_catalog(_catalog(tmp_path, portrait)),
    )
    assert result.rows[1].status is StrategySelectionProbeStatus.NO_STRATEGY_PORTRAIT_CANDIDATE
    assert result.rows[1].strategy_id is None
    output = tmp_path / "result.json"
    write_strategy_selection_probe_result(result, output)
    first = output.read_text(encoding="utf-8")
    write_strategy_selection_probe_result(result, output)
    assert output.read_text(encoding="utf-8") == first
    payload = json.loads(first)
    assert payload["rows"][1]["observation_status"] == "no_strategy_portrait_candidate"
    assert "exited" not in first


def test_textured_nonmatch_remains_unresolved(tmp_path: Path) -> None:
    portrait = _portrait()
    frame_path = _image(tmp_path, portrait)
    frame = load_bgr_image(frame_path)
    frame[486:556, 617:705] = np.random.default_rng(42).integers(
        0, 255, size=(70, 88, 3), dtype=np.uint8
    )
    write_bgr_png(frame_path, frame)

    result = probe_strategy_selection_image(
        frame_path, load_visual_reference_catalog(_catalog(tmp_path, portrait))
    )

    assert result.rows[1].status is StrategySelectionProbeStatus.UNRESOLVED_STRATEGY
    assert result.rows[1].strategy_id is None
