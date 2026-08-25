"""Identity-free player profile-avatar evidence from a selection-final frame.

This module deliberately extracts the player profile avatar separately from the
strategy-initiator portrait.  It carries no participant, tag, self, strategy,
or runtime-slot assertion; callers bind its selection-screen geometry to
already trusted session facts before using the existing runtime-avatar matcher.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from sentry_copilot.capture.frame_source import Frame, FrameSourceType, ImageArray
from sentry_copilot.domain.identifiers import SessionParticipantId
from sentry_copilot.vision.runtime_profile_avatar import SessionProfileAvatarReference
from sentry_copilot.vision.strategy_selection_observations import (
    StrategySelectionCandidateObservation,
)
from sentry_copilot.vision.viewport import ContentViewport, PixelRoi

JP_MUMU_SELECTION_PROFILE_AVATAR_PROFILE_ID = "jp_mumu_fullscreen_1920x1080.profile_avatars.v1"
"""Calibrated only for the explicitly supplied full-frame JP MuMu baseline."""

_JP_MUMU_WIDTH = 1920
_JP_MUMU_HEIGHT = 1080
_PROFILE_AVATAR_X = 155
_PROFILE_AVATAR_FIRST_Y = 316
_PROFILE_AVATAR_STEP_Y = 154
_PROFILE_AVATAR_WIDTH = 92
_PROFILE_AVATAR_HEIGHT = 92
_ROWS = (1, 2, 3, 4)


@dataclass(frozen=True)
class SelectionProfileAvatarEvidence:
    """One immutable selection-row player-avatar crop with copied frame provenance."""

    selection_row: int
    pixel_bounds: PixelRoi
    frame_id: str
    frame_index: int
    processed_at: datetime
    source_timestamp: timedelta | None
    source_type: FrameSourceType
    source_id: str
    source_reference: str
    image: ImageArray

    def __post_init__(self) -> None:
        if self.selection_row not in _ROWS:
            raise ValueError("selection profile-avatar row must be between 1 and 4")
        if not (
            self.frame_id.strip()
            and self.source_id.strip()
            and self.source_reference.strip()
        ):
            raise ValueError("selection profile-avatar provenance text fields must not be blank")
        if self.frame_index < 0:
            raise ValueError("selection profile-avatar frame index must be non-negative")
        if self.processed_at.tzinfo is None or self.processed_at.utcoffset() is None:
            raise ValueError("selection profile-avatar processing time must be timezone-aware")
        if self.source_timestamp is not None and self.source_timestamp.total_seconds() < 0:
            raise ValueError("selection profile-avatar source timestamp must be non-negative")
        if self.image.dtype != np.uint8 or self.image.ndim != 3 or self.image.shape[2] != 3:
            raise ValueError("selection profile-avatar image must be a uint8 BGR image")
        if self.image.shape[:2] != (self.pixel_bounds.height, self.pixel_bounds.width):
            raise ValueError("selection profile-avatar image dimensions must match pixel bounds")
        payload = np.array(self.image, dtype=np.uint8, copy=True)
        payload.setflags(write=False)
        object.__setattr__(self, "image", payload)


@dataclass(frozen=True)
class SelectionStrategyProfileAvatarEvidence:
    """Two independent visual streams joined only by their selection row."""

    strategy: StrategySelectionCandidateObservation
    profile_avatar: SelectionProfileAvatarEvidence

    def __post_init__(self) -> None:
        if self.strategy.selection_row != self.profile_avatar.selection_row:
            raise ValueError("strategy and profile-avatar evidence must share a selection row")


@dataclass(frozen=True)
class SelectionRowParticipantBinding:
    """Caller-owned trusted identity metadata for one selection row, never visual recognition."""

    selection_row: int
    session_player_id: SessionParticipantId

    def __post_init__(self) -> None:
        if self.selection_row not in _ROWS:
            raise ValueError("selection participant binding row must be between 1 and 4")


def selection_profile_avatar_roi(selection_row: int) -> PixelRoi:
    """Return fixed selection-screen player-avatar geometry, not a runtime slot geometry."""

    if selection_row not in _ROWS:
        raise ValueError("selection profile-avatar row must be between 1 and 4")
    return PixelRoi(
        x=_PROFILE_AVATAR_X,
        y=_PROFILE_AVATAR_FIRST_Y + _PROFILE_AVATAR_STEP_Y * (selection_row - 1),
        width=_PROFILE_AVATAR_WIDTH,
        height=_PROFILE_AVATAR_HEIGHT,
    )


def observe_jp_mumu_selection_profile_avatars(
    frame: Frame,
    viewport: ContentViewport,
) -> tuple[SelectionProfileAvatarEvidence, ...]:
    """Extract four profile-avatar crops from one explicit 1920x1080 selection frame."""

    viewport.validate_frame(frame)
    expected_viewport = PixelRoi(x=0, y=0, width=_JP_MUMU_WIDTH, height=_JP_MUMU_HEIGHT)
    if (
        (frame.width, frame.height) != (_JP_MUMU_WIDTH, _JP_MUMU_HEIGHT)
        or viewport.pixel_roi != expected_viewport
    ):
        raise ValueError(
            "selection profile-avatar extraction requires a full 1920x1080 JP MuMu viewport"
        )
    return tuple(_evidence(frame, selection_row) for selection_row in _ROWS)


def join_selection_strategy_profile_avatar_evidence(
    strategy_rows: tuple[StrategySelectionCandidateObservation, ...],
    profile_avatars: tuple[SelectionProfileAvatarEvidence, ...],
) -> tuple[SelectionStrategyProfileAvatarEvidence, ...]:
    """Join independent visual rows by selection geometry without assigning participants."""

    strategy_by_row = _index_strategy_rows(strategy_rows)
    avatar_by_row = _index_profile_avatar_rows(profile_avatars)
    if set(strategy_by_row) != set(avatar_by_row):
        raise ValueError("strategy and profile-avatar evidence must cover the same selection rows")
    return tuple(
        SelectionStrategyProfileAvatarEvidence(strategy_by_row[row], avatar_by_row[row])
        for row in sorted(strategy_by_row)
    )


def bind_selection_profile_avatars_to_participants(
    profile_avatars: tuple[SelectionProfileAvatarEvidence, ...],
    bindings: tuple[SelectionRowParticipantBinding, ...],
) -> tuple[SessionProfileAvatarReference, ...]:
    """Adapt identity-free selection crops to existing session-local matcher references."""

    avatar_by_row = _index_profile_avatar_rows(profile_avatars)
    binding_by_row = _index_binding_rows(bindings)
    if set(avatar_by_row) != set(binding_by_row):
        raise ValueError(
            "selection participant bindings must cover exactly the supplied avatar rows"
        )
    participant_ids = tuple(binding.session_player_id for binding in bindings)
    if len(participant_ids) != len(set(participant_ids)):
        raise ValueError("selection participant bindings must have unique participants")
    return tuple(
        SessionProfileAvatarReference(
            session_player_id=binding_by_row[row].session_player_id,
            frame_id=avatar_by_row[row].frame_id,
            source_reference=avatar_by_row[row].source_reference,
            pixel_bounds=avatar_by_row[row].pixel_bounds,
            image=avatar_by_row[row].image,
        )
        for row in sorted(avatar_by_row)
    )


def _evidence(frame: Frame, selection_row: int) -> SelectionProfileAvatarEvidence:
    roi = selection_profile_avatar_roi(selection_row)
    image = np.array(frame.image[roi.y : roi.bottom, roi.x : roi.right], dtype=np.uint8, copy=True)
    return SelectionProfileAvatarEvidence(
        selection_row=selection_row,
        pixel_bounds=roi,
        frame_id=frame.frame_id,
        frame_index=frame.frame_index,
        processed_at=frame.processed_at,
        source_timestamp=frame.source_timestamp,
        source_type=frame.source_type,
        source_id=frame.source_id,
        source_reference=frame.source_reference,
        image=image,
    )


def _index_strategy_rows(
    items: tuple[StrategySelectionCandidateObservation, ...],
) -> dict[int, StrategySelectionCandidateObservation]:
    values: dict[int, StrategySelectionCandidateObservation] = {}
    for item in items:
        if item.selection_row in values:
            raise ValueError("strategy rows must be unique")
        values[item.selection_row] = item
    return values


def _index_profile_avatar_rows(
    items: tuple[SelectionProfileAvatarEvidence, ...],
) -> dict[int, SelectionProfileAvatarEvidence]:
    values: dict[int, SelectionProfileAvatarEvidence] = {}
    for item in items:
        if item.selection_row in values:
            raise ValueError("profile-avatar rows must be unique")
        values[item.selection_row] = item
    return values


def _index_binding_rows(
    items: tuple[SelectionRowParticipantBinding, ...],
) -> dict[int, SelectionRowParticipantBinding]:
    values: dict[int, SelectionRowParticipantBinding] = {}
    for item in items:
        if item.selection_row in values:
            raise ValueError("selection participant binding rows must be unique")
        values[item.selection_row] = item
    return values
