"""Fixed-layout JP MuMu OPERATION map-code evidence, without gameplay interpretation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from sentry_copilot.capture.frame_source import Frame, FrameSourceType
from sentry_copilot.vision.ocr import OcrBackend, OcrResult, OcrStatus, recognize_text
from sentry_copilot.vision.selection_session_lifecycle import (
    OperationTerminalState,
    observe_jp_mumu_operation_terminal,
)
from sentry_copilot.vision.viewport import ContentViewport, PixelRoi


class OperationMapState(StrEnum):
    OBSERVED = "observed"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class OperationMapObservation:
    """Immutable stage-code fact and OCR provenance from one OPERATION frame."""

    state: OperationMapState
    map_code: str | None
    difficulty_id: str | None
    observed_difficulty: str | None
    processed_at: datetime
    source_timestamp: timedelta | None
    frame_id: str
    frame_index: int
    source_type: FrameSourceType
    source_id: str
    source_reference: str
    map_code_ocr: OcrResult | None
    difficulty_ocr: OcrResult | None

    def __post_init__(self) -> None:
        if not self.frame_id or not self.source_id or not self.source_reference:
            raise ValueError("operation map observation provenance must not be blank")
        if self.state is OperationMapState.OBSERVED:
            if self.map_code is None or self.map_code_ocr is None:
                raise ValueError(
                    "observed operation map requires normalized map code and OCR evidence"
                )
        elif any(
            item is not None
            for item in (
                self.map_code,
                self.difficulty_id,
                self.observed_difficulty,
            )
        ):
            raise ValueError(
                "unresolved operation map observation must not contain inferred values"
            )


JP_MUMU_OPERATION_MAP_PROFILE_ID = "jp_mumu_fullscreen_1920x1080.operation_map.v1"
"""Explicit calibration profile for the initial JP MuMu fullscreen target."""

JP_MUMU_OPERATION_MAP_CODE_ROI = PixelRoi(x=720, y=500, width=480, height=140)
JP_MUMU_OPERATION_DIFFICULTY_ROI = PixelRoi(x=780, y=670, width=360, height=120)


async def observe_jp_mumu_operation_map(
    frame: Frame,
    viewport: ContentViewport,
    backend: OcrBackend,
) -> OperationMapObservation:
    """Read bounded map code/difficulty OCR only after generic OPERATION evidence is present.

    The lower text region is difficulty evidence, not a localized battlefield name. Only the
    retained, calibrated `死地` label is normalized; other OCR leaves difficulty unresolved.
    """

    terminal = observe_jp_mumu_operation_terminal(frame, viewport)
    if terminal.state is not OperationTerminalState.PRESENT:
        return _unresolved(frame)
    code_ocr = await recognize_text(
        frame,
        viewport,
        JP_MUMU_OPERATION_MAP_CODE_ROI,
        backend,
        language_tag="ja-JP",
    )
    difficulty_ocr = await recognize_text(
        frame,
        viewport,
        JP_MUMU_OPERATION_DIFFICULTY_ROI,
        backend,
        language_tag="ja-JP",
    )
    map_code = normalize_operation_map_code(code_ocr.normalized_text)
    if code_ocr.status is not OcrStatus.RECOGNIZED or map_code is None:
        return _unresolved(frame, map_code_ocr=code_ocr, difficulty_ocr=difficulty_ocr)
    candidate_difficulty = _normalize_difficulty(difficulty_ocr.normalized_text)
    difficulty_id = _difficulty_id_for(candidate_difficulty)
    return OperationMapObservation(
        state=OperationMapState.OBSERVED,
        map_code=map_code,
        difficulty_id=difficulty_id,
        observed_difficulty=candidate_difficulty if difficulty_id is not None else None,
        processed_at=frame.processed_at,
        source_timestamp=frame.source_timestamp,
        frame_id=frame.frame_id,
        frame_index=frame.frame_index,
        source_type=frame.source_type,
        source_id=frame.source_id,
        source_reference=frame.source_reference,
        map_code_ocr=code_ocr,
        difficulty_ocr=difficulty_ocr,
    )


def normalize_operation_map_code(value: str | None) -> str | None:
    """Conservatively normalize OCR spacing/punctuation around one stage-code hyphen."""

    if value is None:
        return None
    compact = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    match = re.fullmatch(r"([A-Z]{1,8})(\d{1,3})", compact)
    return f"{match.group(1)}-{match.group(2)}" if match is not None else None


def _normalize_difficulty(value: str | None) -> str | None:
    return value.replace(" ", "") if value else None


def _difficulty_id_for(observed_difficulty: str | None) -> str | None:
    return (
        "difficulty.covenant_latter.deadland"
        if observed_difficulty == "死地"
        else None
    )


def _unresolved(
    frame: Frame,
    *,
    map_code_ocr: OcrResult | None = None,
    difficulty_ocr: OcrResult | None = None,
) -> OperationMapObservation:
    return OperationMapObservation(
        state=OperationMapState.UNRESOLVED,
        map_code=None,
        difficulty_id=None,
        observed_difficulty=None,
        processed_at=frame.processed_at,
        source_timestamp=frame.source_timestamp,
        frame_id=frame.frame_id,
        frame_index=frame.frame_index,
        source_type=frame.source_type,
        source_id=frame.source_id,
        source_reference=frame.source_reference,
        map_code_ocr=map_code_ocr,
        difficulty_ocr=difficulty_ocr,
    )
