"""Fixed-geometry strategy-selection recognition probe for the validated JP baseline."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import cv2
import numpy as np

from sentry_copilot.capture.frame_source import Frame, ImageSequenceFrameSource
from sentry_copilot.image_io import write_bgr_png
from sentry_copilot.vision.local_feature_matching import (
    SELECTION_GRID_RENDER_FEATURE_EXCLUSION_POLICY,
    LocalFeatureMatcherConfig,
    LocalFeatureRejectionReason,
    LocalFeatureVisualMatcher,
    LocalFeatureVisualMatchResult,
)
from sentry_copilot.vision.viewport import PixelRoi
from sentry_copilot.vision.visual_references import VisualMatchStatus, VisualReferenceCatalog

JP_MUMU_1920X1080_PROFILE_ID = "jp_mumu_fullscreen_1920x1080.selection_rows.v1"
_EXPECTED_DIMENSIONS = (1920, 1080)
_ROW_X, _ROW_WIDTH, _ROW_HEIGHT = 593, 184, 184
_ROW_YS = (304, 452, 600, 748)
_PORTRAIT_X, _PORTRAIT_Y, _PORTRAIT_WIDTH, _PORTRAIT_HEIGHT = 24, 34, 88, 70


class StrategySelectionProbeStatus(StrEnum):
    """Vision-only result; it deliberately conveys no player/session semantics."""

    MATCHED_STRATEGY = "matched_strategy"
    UNRESOLVED_STRATEGY = "unresolved_strategy"
    NO_STRATEGY_PORTRAIT_CANDIDATE = "no_strategy_portrait_candidate"


@dataclass(frozen=True)
class StrategySelectionRowObservation:
    selection_row: int
    row_roi: PixelRoi
    portrait_roi: PixelRoi
    status: StrategySelectionProbeStatus
    matcher_result: LocalFeatureVisualMatchResult

    @property
    def strategy_id(self) -> str | None:
        selected = self.matcher_result.selected_identity
        return (
            selected.identity_id
            if self.status is StrategySelectionProbeStatus.MATCHED_STRATEGY and selected
            else None
        )


@dataclass(frozen=True)
class StrategySelectionProbeResult:
    source_image: Path
    image_width: int
    image_height: int
    geometry_profile_id: str
    rows: tuple[StrategySelectionRowObservation, ...]


def probe_strategy_selection_image(
    image_path: str | Path,
    catalog: VisualReferenceCatalog,
    *,
    output_debug_directory: str | Path | None = None,
) -> StrategySelectionProbeResult:
    """Recognize four fixed crops from one explicit 1920x1080 strategy-selection image."""
    source = Path(image_path)
    frame = next(iter(ImageSequenceFrameSource((source,), source_id="strategy-selection-probe")))
    if (frame.width, frame.height) != _EXPECTED_DIMENSIONS:
        raise ValueError(
            "strategy-selection probe requires the validated 1920x1080 JP MuMu baseline; "
            f"received {frame.width}x{frame.height}"
        )
    matcher = LocalFeatureVisualMatcher(
        catalog,
        LocalFeatureMatcherConfig(
            feature_exclusion_policies=(SELECTION_GRID_RENDER_FEATURE_EXCLUSION_POLICY,)
        ),
    )
    rows: list[StrategySelectionRowObservation] = []
    for selection_row, row_y in enumerate(_ROW_YS, start=1):
        row_roi = PixelRoi(_ROW_X, row_y, _ROW_WIDTH, _ROW_HEIGHT)
        portrait_roi = PixelRoi(
            row_roi.x + _PORTRAIT_X, row_roi.y + _PORTRAIT_Y, _PORTRAIT_WIDTH, _PORTRAIT_HEIGHT
        )
        portrait = _crop(frame, portrait_roi)
        match = matcher.match(portrait, query_reference=f"{source}#selection-row-{selection_row}")
        rows.append(
            StrategySelectionRowObservation(
                selection_row, row_roi, portrait_roi, _status(match), match
            )
        )
    result = StrategySelectionProbeResult(
        source, frame.width, frame.height, JP_MUMU_1920X1080_PROFILE_ID, tuple(rows)
    )
    if output_debug_directory is not None:
        _write_debug_images(frame, result, Path(output_debug_directory))
    return result


def write_strategy_selection_probe_result(
    result: StrategySelectionProbeResult, output_path: str | Path
) -> Path:
    """Write deterministic JSON matcher evidence; scores are not confidence values."""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "geometry_profile_id": result.geometry_profile_id,
        "image_height": result.image_height,
        "image_width": result.image_width,
        "rows": [_row_json(row) for row in result.rows],
        "source_image": str(result.source_image),
    }
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return destination


def _crop(frame: Frame, roi: PixelRoi) -> np.ndarray:
    return np.array(frame.image[roi.y : roi.bottom, roi.x : roi.right], dtype=np.uint8, copy=True)


def _status(match: LocalFeatureVisualMatchResult) -> StrategySelectionProbeStatus:
    if match.status is VisualMatchStatus.MATCHED:
        return StrategySelectionProbeStatus.MATCHED_STRATEGY
    if match.reference_candidates and all(
        candidate.rejection_reason is LocalFeatureRejectionReason.QUERY_NO_DESCRIPTORS
        for candidate in match.reference_candidates
    ):
        return StrategySelectionProbeStatus.NO_STRATEGY_PORTRAIT_CANDIDATE
    return StrategySelectionProbeStatus.UNRESOLVED_STRATEGY


def _row_json(row: StrategySelectionRowObservation) -> dict[str, object]:
    selected = row.matcher_result.selected_identity
    candidate = selected.best_reference if selected else None
    return {
        "inlier_ratio": candidate.inlier_ratio if candidate else None,
        "lowe_ratio_matches": candidate.lowe_ratio_match_count if candidate else None,
        "matcher_status": row.matcher_result.status.value,
        "observation_status": row.status.value,
        "portrait_roi": _roi_json(row.portrait_roi),
        "query_keypoints": candidate.query_keypoint_count if candidate else None,
        "ransac_inliers": candidate.ransac_inlier_count if candidate else None,
        "rotation_degrees": candidate.rotation_degrees if candidate else None,
        "row_roi": _roi_json(row.row_roi),
        "scale": candidate.scale if candidate else None,
        "selection_row": row.selection_row,
        "strategy_id": row.strategy_id,
        "top_score": selected.score if selected else None,
        "top_strategy_id": selected.identity_id if selected else None,
    }


def _roi_json(roi: PixelRoi) -> dict[str, int]:
    return {"x": roi.x, "y": roi.y, "width": roi.width, "height": roi.height}


def _write_debug_images(
    frame: Frame, result: StrategySelectionProbeResult, directory: Path
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    annotated = np.array(frame.image, dtype=np.uint8, copy=True)
    for row in result.rows:
        write_bgr_png(directory / f"row-{row.selection_row}-outer.png", _crop(frame, row.row_roi))
        write_bgr_png(
            directory / f"row-{row.selection_row}-portrait.png", _crop(frame, row.portrait_roi)
        )
        cv2.rectangle(
            annotated,
            (row.row_roi.x, row.row_roi.y),
            (row.row_roi.right - 1, row.row_roi.bottom - 1),
            (0, 220, 0),
            1,
        )
    write_bgr_png(directory / "selection-rows-annotated.png", annotated)
