from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from sentry_copilot.vision.validation_runner import (
    NamedNormalizedRoi,
    OfflineValidationConfig,
    parse_named_roi,
    run_offline_validation,
)
from sentry_copilot.vision.viewport import NormalizedRoi, PixelRoi


def _write_source(directory: Path) -> None:
    for index in range(4):
        image = np.full((8, 12, 3), index * 40, dtype=np.uint8)
        assert cv2.imwrite(str(directory / f"frame_{index:02d}.png"), image)


def test_runner_writes_selected_frame_and_named_roi_manifest(tmp_path: Path) -> None:
    source = tmp_path / "synthetic-source"
    source.mkdir()
    _write_source(source)
    output = tmp_path / "validation"

    result = run_offline_validation(
        OfflineValidationConfig(
            source_path=source,
            output_directory=output,
            full_frame=True,
            rois=(NamedNormalizedRoi("center", NormalizedRoi(0.25, 0.25, 0.5, 0.5)),),
            sample_every_n=2,
        )
    )

    records = [json.loads(line) for line in result.manifest_path.read_text().splitlines()]
    assert result.selected_frame_count == 2
    assert result.manifest_record_count == 2
    assert [record["frame_index"] for record in records] == [0, 2]
    assert all(record["roi_name"] == "center" for record in records)
    assert all(Path(record["output_path"]).is_file() for record in records)
    assert all(Path(record["frame_output_path"]).is_file() for record in records)
    assert (output / "frames" / "frame_000002.png").is_file()
    assert (output / "rois" / "frame_000002_center.png").is_file()


def test_runner_uses_explicit_pixel_viewport_and_keeps_frame_source_contract(
    tmp_path: Path,
) -> None:
    source = tmp_path / "synthetic-source"
    source.mkdir()
    _write_source(source)
    output = tmp_path / "validation"

    run_offline_validation(
        OfflineValidationConfig(
            source_path=source,
            output_directory=output,
            viewport_pixel_roi=PixelRoi(x=2, y=1, width=8, height=6),
        )
    )

    record = json.loads((output / "manifest.jsonl").read_text().splitlines()[0])
    assert record["viewport"] == {"height": 6, "width": 8, "x": 2, "y": 1}
    assert record["frame_size"] == {"height": 8, "width": 12}
    assert record["roi_name"] is None


def test_parse_named_roi() -> None:
    parsed = parse_named_roi("hud=0.1,0.2,0.3,0.4")

    assert parsed.name == "hud"
    assert parsed.roi == NormalizedRoi(0.1, 0.2, 0.3, 0.4)
