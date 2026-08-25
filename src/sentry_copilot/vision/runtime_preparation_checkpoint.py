"""Conservative JP MuMu preparation checkpoints and supporting runtime evidence.

This module observes only explicitly supplied 1920x1080 JP MuMu frames.  It does not infer
runtime participation, player identity, strategy identity, or any persistent session state.
The resulting checkpoint is temporal evidence: callers may project its *historical* round-one
HP baseline and a unique self marker into the pure M0.6b1a association input.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import cast

import cv2
import numpy as np

from sentry_copilot.capture.frame_source import Frame, FrameSourceType, ImageArray
from sentry_copilot.domain.identifiers import RuntimeSlotId, SessionId
from sentry_copilot.domain.runtime_association_core import RuntimeSlotAssociationObservation
from sentry_copilot.vision.ocr import OcrBackend, OcrBackendReading, OcrStatus
from sentry_copilot.vision.viewport import ContentViewport, PixelRoi

JP_MUMU_1920_WIDTH = 1920
JP_MUMU_1920_HEIGHT = 1080
JP_MUMU_PREPARATION_LABEL_ROI = PixelRoi(x=845, y=18, width=240, height=65)
JP_MUMU_ROUND_DIGIT_ROI = PixelRoi(x=739, y=35, width=46, height=29)
JP_MUMU_RUNTIME_CARD_X = 34
JP_MUMU_RUNTIME_CARD_Y = 211
JP_MUMU_RUNTIME_CARD_WIDTH = 121
JP_MUMU_RUNTIME_CARD_HEIGHT = 119
JP_MUMU_RUNTIME_CARD_STEP_Y = 145
JP_MUMU_SELF_MARKER_WIDTH = 36
JP_MUMU_SELF_MARKER_HEIGHT = 36
JP_MUMU_HP_RELATIVE_ROIS = (
    PixelRoi(x=56, y=91, width=62, height=28),
    PixelRoi(x=56, y=91, width=62, height=28),
    PixelRoi(x=52, y=89, width=68, height=32),
    PixelRoi(x=51, y=88, width=70, height=34),
    PixelRoi(x=54, y=90, width=68, height=30),
    PixelRoi(x=48, y=86, width=73, height=36),
)
"""Fixed variants around the same bottom-card HP text, not identity-specific tuning."""


class PreparationPhaseStatus(StrEnum):
    PREPARATION = "preparation"
    NOT_PREPARATION = "not_preparation"
    UNRESOLVED = "unresolved"


class PreparationRecognitionMethod(StrEnum):
    PREPARATION_LABEL_OCR = "preparation_label_ocr"
    BATTLE_ENEMY_COUNT_OCR = "battle_enemy_count_ocr"
    UNRESOLVED = "unresolved"


class RoundNumberMethod(StrEnum):
    OCR = "ocr"
    ROUND_ONE_GLYPH = "round_one_glyph"
    UNRESOLVED = "unresolved"


class RuntimeSelfMarkerStatus(StrEnum):
    SELF_MARKER_PRESENT = "self_marker_present"
    SELF_MARKER_ABSENT = "self_marker_absent"
    UNRESOLVED = "unresolved"


class RuntimeSelfMarkerAggregateStatus(StrEnum):
    UNIQUE = "unique"
    UNRESOLVED = "unresolved"
    CONFLICT = "conflict"


class RuntimeHpStatus(StrEnum):
    OBSERVED = "observed"
    UNRESOLVED = "unresolved"
    INVALID = "invalid"


@dataclass(frozen=True)
class CheckpointFrameProvenance:
    """Immutable source provenance copied from one frame."""

    frame_id: str
    frame_index: int
    processed_at: datetime
    source_timestamp: timedelta | None
    source_type: FrameSourceType
    source_id: str
    source_reference: str

    def __post_init__(self) -> None:
        if not (
            self.frame_id.strip()
            and self.source_id.strip()
            and self.source_reference.strip()
        ):
            raise ValueError("checkpoint frame provenance text fields must not be blank")
        if self.frame_index < 0:
            raise ValueError("checkpoint frame index must be non-negative")
        if self.processed_at.tzinfo is None or self.processed_at.utcoffset() is None:
            raise ValueError("checkpoint processing time must be timezone-aware")
        if self.source_timestamp is not None and self.source_timestamp.total_seconds() < 0:
            raise ValueError("checkpoint source timestamp must be non-negative")

    @classmethod
    def from_frame(cls, frame: Frame) -> CheckpointFrameProvenance:
        return cls(
            frame_id=frame.frame_id,
            frame_index=frame.frame_index,
            processed_at=frame.processed_at,
            source_timestamp=frame.source_timestamp,
            source_type=frame.source_type,
            source_id=frame.source_id,
            source_reference=frame.source_reference,
        )


@dataclass(frozen=True)
class RuntimeSlotVisualPosition:
    """Explicit card geometry for a normalized runtime slot ID.

    ``visual_index`` is display geometry only.  It is never a selection row or participant ID.
    """

    runtime_slot_id: RuntimeSlotId
    visual_index: int

    def __post_init__(self) -> None:
        if not 1 <= self.visual_index <= 4:
            raise ValueError("runtime slot visual_index must be between 1 and 4")


@dataclass(frozen=True)
class RuntimePreparationCheckpointRequest:
    """Caller-owned session and runtime-card context for one frame observation."""

    session_id: SessionId
    runtime_slots: tuple[RuntimeSlotVisualPosition, ...]

    def __post_init__(self) -> None:
        if not self.runtime_slots or len(self.runtime_slots) > 4:
            raise ValueError("a checkpoint must contain between one and four runtime slots")
        slot_ids = tuple(item.runtime_slot_id for item in self.runtime_slots)
        indices = tuple(item.visual_index for item in self.runtime_slots)
        if len(slot_ids) != len(set(slot_ids)):
            raise ValueError("checkpoint runtime slot IDs must be unique")
        if len(indices) != len(set(indices)):
            raise ValueError("checkpoint runtime visual indices must be unique")


@dataclass(frozen=True)
class OcrEvidence:
    """One OCR reading with the original source ROI and any fixed scale provenance."""

    pixel_bounds: PixelRoi
    raw_text: str | None
    normalized_text: str | None
    confidence: float | None
    status: OcrStatus
    scale_factor: int = 1
    preprocessing: str = "none"

    def __post_init__(self) -> None:
        if self.scale_factor < 1:
            raise ValueError("OCR scale factor must be positive")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("OCR confidence must be between 0.0 and 1.0")


@dataclass(frozen=True)
class PreparationRecognition:
    status: PreparationPhaseStatus
    method: PreparationRecognitionMethod
    primary_evidence: OcrEvidence

    def __post_init__(self) -> None:
        if self.status is PreparationPhaseStatus.PREPARATION:
            if self.method is not PreparationRecognitionMethod.PREPARATION_LABEL_OCR:
                raise ValueError("preparation requires primary label OCR evidence")
        elif self.status is PreparationPhaseStatus.NOT_PREPARATION:
            if self.method is not PreparationRecognitionMethod.BATTLE_ENEMY_COUNT_OCR:
                raise ValueError("not-preparation requires battle enemy-count OCR evidence")
        elif self.method is not PreparationRecognitionMethod.UNRESOLVED:
            raise ValueError("unresolved preparation requires unresolved method")


@dataclass(frozen=True)
class RoundNumberObservation:
    round_number: int | None
    method: RoundNumberMethod
    evidence: OcrEvidence | None

    def __post_init__(self) -> None:
        if self.round_number is None:
            if self.method is not RoundNumberMethod.UNRESOLVED:
                raise ValueError("unknown round number requires unresolved method")
            return
        if self.round_number < 1:
            raise ValueError("round number must be positive")
        if self.method is RoundNumberMethod.UNRESOLVED or self.evidence is None:
            raise ValueError("known round number requires evidence and a recognition method")


@dataclass(frozen=True)
class RuntimeSelfMarkerObservation:
    runtime_slot_id: RuntimeSlotId
    status: RuntimeSelfMarkerStatus
    pixel_bounds: PixelRoi
    teal_pixel_count: int
    threshold_pixel_count: int

    def __post_init__(self) -> None:
        if self.teal_pixel_count < 0 or self.threshold_pixel_count <= 0:
            raise ValueError("self-marker pixel counts must be non-negative and threshold positive")


@dataclass(frozen=True)
class RuntimeSelfMarkerAggregate:
    status: RuntimeSelfMarkerAggregateStatus
    self_runtime_slot_id: RuntimeSlotId | None
    present_runtime_slot_ids: tuple[RuntimeSlotId, ...]

    def __post_init__(self) -> None:
        if self.status is RuntimeSelfMarkerAggregateStatus.UNIQUE:
            if self.self_runtime_slot_id is None or len(self.present_runtime_slot_ids) != 1:
                raise ValueError("unique self-marker evidence requires exactly one slot")
        elif self.self_runtime_slot_id is not None:
            raise ValueError("non-unique self-marker aggregate cannot select a slot")


@dataclass(frozen=True)
class RuntimeHpObservation:
    runtime_slot_id: RuntimeSlotId
    status: RuntimeHpStatus
    observed_current_hp: int | None
    evidence: tuple[OcrEvidence, ...]

    def __post_init__(self) -> None:
        if self.status is RuntimeHpStatus.OBSERVED:
            if self.observed_current_hp is None or not 0 <= self.observed_current_hp <= 999:
                raise ValueError("observed runtime HP must be between zero and 999")
        elif self.observed_current_hp is not None:
            raise ValueError("unresolved or invalid HP observation cannot contain a numeric value")


@dataclass(frozen=True)
class PreparationCheckpoint:
    """One immutable temporal checkpoint; it is not a player identity authority."""

    session_id: SessionId
    frame: CheckpointFrameProvenance
    viewport: ContentViewport
    preparation: PreparationRecognition
    round_number: RoundNumberObservation
    self_marker: RuntimeSelfMarkerAggregate
    slot_self_markers: tuple[RuntimeSelfMarkerObservation, ...]
    slot_hp: tuple[RuntimeHpObservation, ...]

    def __post_init__(self) -> None:
        self_ids = tuple(item.runtime_slot_id for item in self.slot_self_markers)
        hp_ids = tuple(item.runtime_slot_id for item in self.slot_hp)
        if len(self_ids) != len(set(self_ids)) or len(hp_ids) != len(set(hp_ids)):
            raise ValueError("checkpoint slot observations must be unique")
        if set(self_ids) != set(hp_ids):
            raise ValueError("self-marker and HP observations must cover the same slots")
        if self.viewport.frame_id != self.frame.frame_id:
            raise ValueError("checkpoint viewport must belong to the checkpoint frame")


@dataclass(frozen=True)
class RuntimeInitialHpEvidence:
    """Historical round-one baseline plus latest observed checkpoint HP for one runtime slot."""

    runtime_slot_id: RuntimeSlotId
    known_initial_hp: int | None
    current_hp: int | None
    hp_loss_observed: bool

    def __post_init__(self) -> None:
        if self.known_initial_hp is not None and not 0 <= self.known_initial_hp <= 999:
            raise ValueError("known initial HP must be between zero and 999")
        if self.current_hp is not None and not 0 <= self.current_hp <= 999:
            raise ValueError("current HP must be between zero and 999")
        if self.hp_loss_observed and (
            self.known_initial_hp is None
            or self.current_hp is None
            or self.current_hp >= self.known_initial_hp
        ):
            raise ValueError("HP loss requires a lower current HP and an initial baseline")

    def project_to_association_core(
        self,
        observation: RuntimeSlotAssociationObservation,
    ) -> RuntimeSlotAssociationObservation:
        """Carry only the trustworthy historical baseline into M0.6b1a's HP filter.

        The core's ``current_hp`` field is a legacy normalized carrier when
        ``hp_is_known_initial`` is true.  This intentionally does not project a later current
        HP value, which would make the association core treat a post-loss value as identity data.
        """

        if observation.runtime_slot_id != self.runtime_slot_id:
            raise ValueError("initial-HP evidence belongs to a different runtime slot")
        if self.known_initial_hp is None:
            return observation.model_copy(update={"hp_is_known_initial": False})
        return observation.model_copy(
            update={"current_hp": self.known_initial_hp, "hp_is_known_initial": True}
        )


def runtime_card_roi(visual_index: int) -> PixelRoi:
    """Return the known JP MuMu runtime-card geometry for one explicit visual position."""

    if not 1 <= visual_index <= 4:
        raise ValueError("runtime slot visual_index must be between 1 and 4")
    return PixelRoi(
        x=JP_MUMU_RUNTIME_CARD_X,
        y=JP_MUMU_RUNTIME_CARD_Y + JP_MUMU_RUNTIME_CARD_STEP_Y * (visual_index - 1),
        width=JP_MUMU_RUNTIME_CARD_WIDTH,
        height=JP_MUMU_RUNTIME_CARD_HEIGHT,
    )


async def observe_jp_mumu_preparation_checkpoint(
    frame: Frame,
    viewport: ContentViewport,
    request: RuntimePreparationCheckpointRequest,
    backend: OcrBackend,
    *,
    preparation_language_tag: str = "ja-JP",
    numeric_language_tag: str = "en-US",
    hp_language_tag: str = "ja-JP",
) -> PreparationCheckpoint:
    """Observe one fixed-layout JP MuMu preparation checkpoint conservatively.

    Any unavailable OCR, incompatible viewport, unparseable number, or conflicting self-marker
    evidence is represented as an explicit unresolved result.  The function never mutates the
    frame, caller request, or domain state.
    """

    _validate_known_layout(frame, viewport)
    primary = await _observe_ocr(
        frame,
        JP_MUMU_PREPARATION_LABEL_ROI,
        backend,
        language_tag=preparation_language_tag,
    )
    normalized = primary.normalized_text or ""
    compact = normalized.replace(" ", "")
    if "休憩タイム" in compact:
        preparation = PreparationRecognition(
            status=PreparationPhaseStatus.PREPARATION,
            method=PreparationRecognitionMethod.PREPARATION_LABEL_OCR,
            primary_evidence=primary,
        )
    elif _contains_battle_enemy_count(compact):
        preparation = PreparationRecognition(
            status=PreparationPhaseStatus.NOT_PREPARATION,
            method=PreparationRecognitionMethod.BATTLE_ENEMY_COUNT_OCR,
            primary_evidence=primary,
        )
    else:
        preparation = PreparationRecognition(
            status=PreparationPhaseStatus.UNRESOLVED,
            method=PreparationRecognitionMethod.UNRESOLVED,
            primary_evidence=primary,
        )

    round_observation = await _observe_round_number(
        frame,
        backend,
        language_tag=numeric_language_tag,
        enabled=preparation.status is PreparationPhaseStatus.PREPARATION,
    )
    slot_self_markers = _observe_self_markers_from_frame(frame, request.runtime_slots)
    self_marker = aggregate_runtime_self_markers(slot_self_markers)
    slot_hp = await _observe_runtime_hp_batch(
        frame,
        request.runtime_slots,
        backend,
        language_tag=hp_language_tag,
        enabled=preparation.status is PreparationPhaseStatus.PREPARATION,
    )
    return PreparationCheckpoint(
        session_id=request.session_id,
        frame=CheckpointFrameProvenance.from_frame(frame),
        viewport=viewport,
        preparation=preparation,
        round_number=round_observation,
        self_marker=self_marker,
        slot_self_markers=slot_self_markers,
        slot_hp=slot_hp,
    )


def aggregate_runtime_self_markers(
    observations: tuple[RuntimeSelfMarkerObservation, ...],
) -> RuntimeSelfMarkerAggregate:
    """Keep zero and multiple self-marker claims unresolved rather than choosing a winner."""

    present = tuple(
        item.runtime_slot_id
        for item in observations
        if item.status is RuntimeSelfMarkerStatus.SELF_MARKER_PRESENT
    )
    if len(present) == 1:
        return RuntimeSelfMarkerAggregate(
            status=RuntimeSelfMarkerAggregateStatus.UNIQUE,
            self_runtime_slot_id=present[0],
            present_runtime_slot_ids=present,
        )
    if len(present) > 1:
        return RuntimeSelfMarkerAggregate(
            status=RuntimeSelfMarkerAggregateStatus.CONFLICT,
            self_runtime_slot_id=None,
            present_runtime_slot_ids=present,
        )
    return RuntimeSelfMarkerAggregate(
        status=RuntimeSelfMarkerAggregateStatus.UNRESOLVED,
        self_runtime_slot_id=None,
        present_runtime_slot_ids=(),
    )


def derive_runtime_initial_hp_evidence(
    checkpoints: tuple[PreparationCheckpoint, ...],
) -> tuple[RuntimeInitialHpEvidence, ...]:
    """Derive immutable HP history without ever backfilling a missed round-one baseline.

    Callers provide chronological checkpoints from one session.  A later checkpoint updates only
    ``current_hp``.  It cannot establish or overwrite ``known_initial_hp``.
    """

    if not checkpoints:
        return ()
    session_id = checkpoints[0].session_id
    if any(item.session_id != session_id for item in checkpoints):
        raise ValueError("initial-HP checkpoints must belong to one session")
    values: dict[RuntimeSlotId, RuntimeInitialHpEvidence] = {}
    for checkpoint in checkpoints:
        eligible_baseline = (
            checkpoint.preparation.status is PreparationPhaseStatus.PREPARATION
            and checkpoint.round_number.round_number == 1
        )
        for hp in checkpoint.slot_hp:
            previous = values.get(
                hp.runtime_slot_id,
                RuntimeInitialHpEvidence(
                    runtime_slot_id=hp.runtime_slot_id,
                    known_initial_hp=None,
                    current_hp=None,
                    hp_loss_observed=False,
                ),
            )
            current_hp = previous.current_hp
            initial_hp = previous.known_initial_hp
            if hp.status is RuntimeHpStatus.OBSERVED:
                assert hp.observed_current_hp is not None
                current_hp = hp.observed_current_hp
                if eligible_baseline and initial_hp is None:
                    initial_hp = hp.observed_current_hp
            values[hp.runtime_slot_id] = RuntimeInitialHpEvidence(
                runtime_slot_id=hp.runtime_slot_id,
                known_initial_hp=initial_hp,
                current_hp=current_hp,
                hp_loss_observed=(
                    initial_hp is not None and current_hp is not None and current_hp < initial_hp
                ),
            )
    return tuple(values[slot_id] for slot_id in sorted(values))


def project_unique_self_marker_to_association_core(
    observation: RuntimeSlotAssociationObservation,
    aggregate: RuntimeSelfMarkerAggregate,
) -> RuntimeSlotAssociationObservation:
    """Project only a unique marker; a zero/multiple-marker aggregate has no core claim."""

    if aggregate.status is not RuntimeSelfMarkerAggregateStatus.UNIQUE:
        return observation.model_copy(update={"self_marker": None})
    assert aggregate.self_runtime_slot_id is not None
    return observation.model_copy(
        update={"self_marker": observation.runtime_slot_id == aggregate.self_runtime_slot_id}
    )


async def _observe_round_number(
    frame: Frame,
    backend: OcrBackend,
    *,
    language_tag: str,
    enabled: bool,
) -> RoundNumberObservation:
    if not enabled:
        return RoundNumberObservation(
            round_number=None,
            method=RoundNumberMethod.UNRESOLVED,
            evidence=None,
        )
    evidence = await _observe_ocr(
        frame,
        JP_MUMU_ROUND_DIGIT_ROI,
        backend,
        language_tag=language_tag,
        scale_factor=2,
    )
    parsed = _parse_exact_positive_integer(evidence.normalized_text)
    if parsed is not None:
        return RoundNumberObservation(
            round_number=parsed,
            method=RoundNumberMethod.OCR,
            evidence=evidence,
        )
    if _matches_round_one_glyph(frame.image[35:64, 739:785]):
        return RoundNumberObservation(
            round_number=1,
            method=RoundNumberMethod.ROUND_ONE_GLYPH,
            evidence=evidence,
        )
    return RoundNumberObservation(
        round_number=None,
        method=RoundNumberMethod.UNRESOLVED,
        evidence=evidence,
    )


async def _observe_runtime_hp_batch(
    frame: Frame,
    positions: tuple[RuntimeSlotVisualPosition, ...],
    backend: OcrBackend,
    *,
    language_tag: str,
    enabled: bool,
) -> tuple[RuntimeHpObservation, ...]:
    observations: list[RuntimeHpObservation] = []
    for position in positions:
        observations.append(
            await _observe_runtime_hp(
                frame,
                position,
                backend,
                language_tag=language_tag,
                enabled=enabled,
            )
        )
    return tuple(observations)


async def _observe_runtime_hp(
    frame: Frame,
    position: RuntimeSlotVisualPosition,
    backend: OcrBackend,
    *,
    language_tag: str,
    enabled: bool,
) -> RuntimeHpObservation:
    if not enabled:
        return RuntimeHpObservation(
            runtime_slot_id=position.runtime_slot_id,
            status=RuntimeHpStatus.UNRESOLVED,
            observed_current_hp=None,
            evidence=(),
        )
    card = runtime_card_roi(position.visual_index)
    readings: list[OcrEvidence] = []
    strong_values: list[int] = []
    weak_values: list[int] = []
    has_out_of_range_value = False
    for index, relative in enumerate(JP_MUMU_HP_RELATIVE_ROIS):
        roi = PixelRoi(
            x=card.x + relative.x,
            y=card.y + relative.y,
            width=relative.width,
            height=relative.height,
        )
        preprocessing = "none" if index < 4 else "grayscale"
        reading = await _observe_ocr(
            frame,
            roi,
            backend,
            language_tag=language_tag,
            scale_factor=4 if index == 1 else 6,
            preprocessing=preprocessing,
        )
        readings.append(reading)
        normalized = reading.normalized_text
        if normalized is not None and re.fullmatch(r"\d+", normalized) is not None:
            has_out_of_range_value = int(normalized) > 999
        parsed = _parse_hp_candidate(reading.normalized_text)
        if parsed is not None:
            value, exact = parsed
            (strong_values if exact else weak_values).append(value)
    strong_distinct = set(strong_values)
    weak_distinct = set(weak_values)
    if len(strong_distinct) == 1:
        return RuntimeHpObservation(
            runtime_slot_id=position.runtime_slot_id,
            status=RuntimeHpStatus.OBSERVED,
            observed_current_hp=next(iter(strong_distinct)),
            evidence=tuple(readings),
        )
    if not strong_distinct and len(weak_distinct) == 1 and len(weak_values) >= 2:
        return RuntimeHpObservation(
            runtime_slot_id=position.runtime_slot_id,
            status=RuntimeHpStatus.OBSERVED,
            observed_current_hp=next(iter(weak_distinct)),
            evidence=tuple(readings),
        )
    status = (
        RuntimeHpStatus.INVALID
        if has_out_of_range_value or len(strong_distinct) > 1 or len(weak_distinct) > 1
        else RuntimeHpStatus.UNRESOLVED
    )
    return RuntimeHpObservation(
        runtime_slot_id=position.runtime_slot_id,
        status=status,
        observed_current_hp=None,
        evidence=tuple(readings),
    )


async def _observe_ocr(
    frame: Frame,
    roi: PixelRoi,
    backend: OcrBackend,
    *,
    language_tag: str,
    scale_factor: int = 1,
    preprocessing: str = "none",
) -> OcrEvidence:
    crop = np.array(
        frame.image[roi.y : roi.bottom, roi.x : roi.right], dtype=np.uint8, copy=True
    )
    if preprocessing == "grayscale":
        crop = cast(
            ImageArray,
            cv2.cvtColor(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR),
        )
    elif preprocessing != "none":
        raise ValueError(f"unsupported OCR preprocessing: {preprocessing}")
    if scale_factor != 1:
        crop = cast(
            ImageArray,
            cv2.resize(
                crop,
                None,
                fx=scale_factor,
                fy=scale_factor,
                interpolation=cv2.INTER_CUBIC,
            ),
        )
    crop = np.ascontiguousarray(crop, dtype=np.uint8)
    crop.setflags(write=False)
    reading = await backend.recognize(crop, language_tag=language_tag)
    normalized = _normalize_text(reading.raw_text)
    return OcrEvidence(
        pixel_bounds=roi,
        raw_text=reading.raw_text,
        normalized_text=normalized,
        confidence=reading.confidence,
        status=_ocr_status(reading, normalized),
        scale_factor=scale_factor,
        preprocessing=preprocessing,
    )


def _observe_self_markers_from_frame(
    frame: Frame,
    positions: tuple[RuntimeSlotVisualPosition, ...],
) -> tuple[RuntimeSelfMarkerObservation, ...]:
    result: list[RuntimeSelfMarkerObservation] = []
    for position in positions:
        card = runtime_card_roi(position.visual_index)
        roi = PixelRoi(
            x=card.x,
            y=card.y,
            width=JP_MUMU_SELF_MARKER_WIDTH,
            height=JP_MUMU_SELF_MARKER_HEIGHT,
        )
        image = frame.image[roi.y : roi.bottom, roi.x : roi.right]
        blue, green, red = image[:, :, 0], image[:, :, 1], image[:, :, 2]
        teal_pixels = int(((blue > 90) & (green > 160) & (red < 150)).sum())
        result.append(
            RuntimeSelfMarkerObservation(
                runtime_slot_id=position.runtime_slot_id,
                status=(
                    RuntimeSelfMarkerStatus.SELF_MARKER_PRESENT
                    if teal_pixels >= 300
                    else RuntimeSelfMarkerStatus.SELF_MARKER_ABSENT
                ),
                pixel_bounds=roi,
                teal_pixel_count=teal_pixels,
                threshold_pixel_count=300,
            )
        )
    return tuple(result)


def _validate_known_layout(frame: Frame, viewport: ContentViewport) -> None:
    viewport.validate_frame(frame)
    if (
        viewport.pixel_roi != PixelRoi(
            x=0,
            y=0,
            width=JP_MUMU_1920_WIDTH,
            height=JP_MUMU_1920_HEIGHT,
        )
    ):
        raise ValueError("JP MuMu preparation checkpoint requires a full 1920x1080 viewport")


def _contains_battle_enemy_count(text: str) -> bool:
    return re.search(r"\d+\s*/\s*\d+", text) is not None


def _parse_exact_positive_integer(text: str | None) -> int | None:
    if text is None or re.fullmatch(r"\d+", text) is None:
        return None
    value = int(text)
    return value if value >= 1 else None


def _parse_hp_candidate(text: str | None) -> tuple[int, bool] | None:
    if text is None:
        return None
    # A solitary non-zero digit is too easily produced by a clipped two-digit overlay.  Zero is
    # still meaningful for a later runtime checkpoint, while the current initial-HP UI range is
    # represented by two or three digits.
    if text == "0" or re.fullmatch(r"\d{2,3}", text) is not None:
        return int(text), True
    values = [int(item) for item in re.findall(r"(?<!\d)\d{2,3}(?!\d)", text)]
    if len(values) != 1 or not 0 <= values[0] <= 999:
        return None
    return values[0], False


def _normalize_text(raw_text: str | None) -> str | None:
    if raw_text is None:
        return None
    return " ".join(unicodedata.normalize("NFKC", raw_text).split())


def _ocr_status(reading: OcrBackendReading, normalized: str | None) -> OcrStatus:
    if reading.raw_text is None:
        return OcrStatus.UNKNOWN
    return OcrStatus.RECOGNIZED if normalized else OcrStatus.EMPTY


def _matches_round_one_glyph(image: ImageArray) -> bool:
    """Recognize the calibrated round-one glyph only when its strict shape is present.

    Windows OCR reliably reads multi-digit round labels in the calibration set but can return an
    empty value for a solitary ``1``.  This is a deliberately narrow visual fallback, not a
    generic digit guess: it requires exactly one tall, narrow interior dark component in the
    known round-number cell.  Other numbers remain OCR-only and therefore unresolved on failure.
    """

    if image.shape != (29, 46, 3):
        return False
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    interior = (gray < 80).astype(np.uint8)
    interior[:4, :] = 0
    interior[-4:, :] = 0
    component_count, _, stats, _ = cv2.connectedComponentsWithStats(interior, connectivity=8)
    components = [
        tuple(int(value) for value in row)
        for row in stats[1:component_count]
        if row[4] >= 20
    ]
    if len(components) != 1:
        return False
    x, y, width, height, area = components[0]
    return 18 <= x <= 25 and 4 <= y <= 7 and 5 <= width <= 10 and 18 <= height <= 23 and area >= 45
