from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import numpy as np
import pytest

from sentry_copilot.capture.frame_source import Frame, FrameSourceType
from sentry_copilot.domain.enums import EvidenceKind
from sentry_copilot.vision.local_feature_matching import LocalFeatureVisualMatchResult
from sentry_copilot.vision.selection_profile_avatar import (
    SelectionProfileAvatarEvidence,
    SelectionRowParticipantBinding,
    bind_selection_profile_avatars_to_participants,
    join_selection_strategy_profile_avatar_evidence,
    observe_jp_mumu_selection_profile_avatars,
    selection_profile_avatar_roi,
)
from sentry_copilot.vision.strategy_selection_observations import (
    StrategySelectionCandidateObservation,
)
from sentry_copilot.vision.strategy_selection_probe import StrategySelectionProbeStatus
from sentry_copilot.vision.viewport import ContentViewport, PixelRoi


def _frame() -> Frame:
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    for row in range(1, 5):
        roi = selection_profile_avatar_roi(row)
        image[roi.y : roi.bottom, roi.x : roi.right] = (row, row + 10, row + 20)
    return Frame(
        frame_id="selection:000001",
        frame_index=1,
        processed_at=datetime(2026, 8, 25, tzinfo=UTC),
        source_timestamp=None,
        source_type=FrameSourceType.IMAGE_SEQUENCE,
        source_id="selection",
        width=1920,
        height=1080,
        image=image,
        source_reference="synthetic-selection.png",
    )


def _strategy(row: int) -> StrategySelectionCandidateObservation:
    return StrategySelectionCandidateObservation(
        selection_row=row,
        strategy_id=f"strategy.synthetic.{row}",
        vision_status=StrategySelectionProbeStatus.MATCHED_STRATEGY,
        provenance=EvidenceKind.OBSERVED,
        source="synthetic",
        matcher_result=cast(LocalFeatureVisualMatchResult, object()),
    )


def test_extracts_four_identity_free_avatars_with_fixed_geometry_and_provenance() -> None:
    frame = _frame()

    evidence = observe_jp_mumu_selection_profile_avatars(frame, ContentViewport.full_frame(frame))

    assert [item.selection_row for item in evidence] == [1, 2, 3, 4]
    assert [item.pixel_bounds for item in evidence] == [
        PixelRoi(x=155, y=316, width=92, height=92),
        PixelRoi(x=155, y=470, width=92, height=92),
        PixelRoi(x=155, y=624, width=92, height=92),
        PixelRoi(x=155, y=778, width=92, height=92),
    ]
    assert all(item.frame_id == frame.frame_id for item in evidence)
    assert all(item.source_reference == "synthetic-selection.png" for item in evidence)
    assert all(
        item.image.shape == (92, 92, 3) and not item.image.flags.writeable for item in evidence
    )
    assert not frame.image.flags.writeable
    assert not hasattr(evidence[0], "session_player_id")
    assert not hasattr(evidence[0], "strategy_id")
    with pytest.raises(ValueError, match="assignment destination is read-only"):
        evidence[0].image[0, 0] = 0


def test_rejects_non_baseline_viewport_and_never_interprets_rows_as_slots() -> None:
    frame = _frame()
    wrong_viewport = ContentViewport(
        frame_id=frame.frame_id,
        frame_width=frame.width,
        frame_height=frame.height,
        pixel_roi=PixelRoi(x=1, y=0, width=1919, height=1080),
    )

    with pytest.raises(ValueError, match="full 1920x1080"):
        observe_jp_mumu_selection_profile_avatars(frame, wrong_viewport)
    assert selection_profile_avatar_roi(3) == PixelRoi(x=155, y=624, width=92, height=92)


def test_joins_strategy_and_avatar_by_selection_row_then_explicitly_binds_participants() -> None:
    frame = _frame()
    avatars = observe_jp_mumu_selection_profile_avatars(frame, ContentViewport.full_frame(frame))
    joined = join_selection_strategy_profile_avatar_evidence(
        tuple(_strategy(row) for row in (4, 2, 1, 3)), avatars
    )
    references = bind_selection_profile_avatars_to_participants(
        avatars,
        (
            SelectionRowParticipantBinding(selection_row=1, session_player_id="participant.c"),
            SelectionRowParticipantBinding(selection_row=2, session_player_id="participant.a"),
            SelectionRowParticipantBinding(selection_row=3, session_player_id="participant.d"),
            SelectionRowParticipantBinding(selection_row=4, session_player_id="participant.b"),
        ),
    )

    assert [item.strategy.selection_row for item in joined] == [1, 2, 3, 4]
    assert [item.strategy.strategy_id for item in joined] == [
        "strategy.synthetic.1",
        "strategy.synthetic.2",
        "strategy.synthetic.3",
        "strategy.synthetic.4",
    ]
    assert [item.session_player_id for item in references] == [
        "participant.c",
        "participant.a",
        "participant.d",
        "participant.b",
    ]
    assert [item.pixel_bounds for item in references] == [item.pixel_bounds for item in avatars]


def test_binding_rejects_duplicate_or_mismatched_rows_without_overwrite() -> None:
    frame = _frame()
    avatars = observe_jp_mumu_selection_profile_avatars(frame, ContentViewport.full_frame(frame))

    with pytest.raises(ValueError, match="unique"):
        bind_selection_profile_avatars_to_participants(
            avatars,
            (
                SelectionRowParticipantBinding(selection_row=1, session_player_id="participant.a"),
                SelectionRowParticipantBinding(selection_row=1, session_player_id="participant.b"),
            ),
        )
    with pytest.raises(ValueError, match="cover exactly"):
        bind_selection_profile_avatars_to_participants(
            avatars[:3],
            tuple(
                SelectionRowParticipantBinding(
                    selection_row=row, session_player_id=f"participant.{row}"
                )
                for row in range(1, 5)
            ),
        )


def test_join_rejects_row_mismatch() -> None:
    frame = _frame()
    avatars = observe_jp_mumu_selection_profile_avatars(frame, ContentViewport.full_frame(frame))
    with pytest.raises(ValueError, match="cover the same"):
        join_selection_strategy_profile_avatar_evidence((_strategy(1),), avatars)


def test_evidence_rejects_naive_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        SelectionProfileAvatarEvidence(
            selection_row=1,
            pixel_bounds=PixelRoi(x=0, y=0, width=1, height=1),
            frame_id="frame",
            frame_index=0,
            processed_at=datetime(2026, 8, 25),
            source_timestamp=None,
            source_type=FrameSourceType.IMAGE_SEQUENCE,
            source_id="source",
            source_reference="source.png",
            image=np.zeros((1, 1, 3), dtype=np.uint8),
        )
