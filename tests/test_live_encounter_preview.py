from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime

import numpy as np

from sentry_copilot.capture.frame_source import (
    Frame,
    FrameSource,
    FrameSourceMetadata,
    FrameSourceType,
)
from sentry_copilot.encounter.catalog import EncounterMapCatalog
from sentry_copilot.encounter.models import DifficultyDefinition, LocalizedText
from sentry_copilot.encounter.session import EncounterUpdateStatus
from sentry_copilot.services.live_encounter_preview import (
    LIVE_ENCOUNTER_PREVIEW_BUILD,
    LiveEncounterPreviewController,
    LiveEncounterPreviewSnapshot,
    LiveEncounterPreviewStatus,
    run_live_encounter_loop,
)
from sentry_copilot.vision.ocr import OcrBackendReading
from sentry_copilot.vision.operation_difficulty import (
    OperationDifficultyObservation,
    observe_jp_mumu_operation_difficulty,
)
from sentry_copilot.vision.outside_run_pages import (
    OutsideRunPageKind,
    OutsideRunPageObservation,
    OutsideRunPageObservationMethod,
    OutsideRunPageState,
)
from sentry_copilot.vision.viewport import ContentViewport


class _QueueOcrBackend:
    def __init__(self, readings: list[str | None]) -> None:
        self._readings = iter(readings)

    async def recognize(self, image: np.ndarray, *, language_tag: str) -> OcrBackendReading:
        del image
        assert language_tag == "ja-JP"
        return OcrBackendReading(next(self._readings))


class _Frames(FrameSource):
    def __init__(self, frames: tuple[Frame, ...]) -> None:
        self._frames = frames

    @property
    def metadata(self) -> FrameSourceMetadata:
        return FrameSourceMetadata(
            source_id="synthetic-live",
            source_type=FrameSourceType.WINDOWS_DISPLAY,
            source_reference="synthetic-display",
            frame_rate=2.0,
        )

    def frames(self) -> Iterator[Frame]:
        return iter(self._frames)


def _frame(index: int = 0, *, size: tuple[int, int] = (1920, 1080)) -> Frame:
    width, height = size
    image = np.zeros((height, width, 3), dtype=np.uint8)
    if size == (1920, 1080):
        image[500:640, 720:1200] = (255, 255, 255)
    return Frame(
        frame_id=f"synthetic-live:{index:06d}",
        frame_index=index,
        processed_at=datetime(2026, 8, 28, tzinfo=UTC),
        source_timestamp=None,
        source_type=FrameSourceType.WINDOWS_DISPLAY,
        source_id="synthetic-live",
        source_reference="synthetic-display",
        width=width,
        height=height,
        image=image,
    )


def _process(
    controller: LiveEncounterPreviewController, frame: Frame
) -> LiveEncounterPreviewSnapshot:
    return asyncio.run(controller.process_frame(frame))


def test_live_controller_is_single_encounter_per_process_and_starts_empty() -> None:
    controller = LiveEncounterPreviewController(_QueueOcrBackend([]))

    initial = controller.snapshot()
    assert initial.presentation.progress_label == "0 / 4"
    assert initial.status is LiveEncounterPreviewStatus.WAITING_FOR_SUPPORTED_FRAME
    assert initial.presentation.items[1].implemented is False
    assert initial.presentation.items[1].value == "本版本暂未支持"
    assert not hasattr(controller, "new_encounter")

    replacement_process = LiveEncounterPreviewController(_QueueOcrBackend([]))
    assert replacement_process.session.encounter_id == initial.session.encounter_id
    assert replacement_process.snapshot().presentation.progress_label == "0 / 4"


def test_live_controller_handles_supported_frames_without_erasing_or_duplicate_state() -> None:
    controller = LiveEncounterPreviewController(
        _QueueOcrBackend(["AC-3", "未校准", "AC-3", "死地", "AC-3", "死地", "AC-3", "未校准"])
    )

    unsupported = _process(controller, _frame(size=(1280, 720)))
    assert unsupported.status is LiveEncounterPreviewStatus.WAITING_FOR_SUPPORTED_FRAME
    assert unsupported.presentation.progress_label == "0 / 4"

    initial = _process(controller, _frame(1))
    assert initial.presentation.progress_label == "0 / 4"
    assert initial.latest_map_id is None
    assert initial.latest_difficulty_id is None

    enriched = _process(controller, _frame(2))
    assert enriched.presentation.progress_label == "0 / 4"
    assert enriched.latest_difficulty_id == "difficulty.covenant_latter.deadland"
    assert enriched.presentation.difficulty_value == "死地"

    repeated = _process(controller, _frame(3))
    weak_later = _process(controller, _frame(4))
    assert repeated.session == enriched.session
    assert weak_later.session == enriched.session


def test_live_controller_presentation_locale_only_changes_the_view_and_diagnostics_are_local() -> (
    None
):
    controller = LiveEncounterPreviewController(_QueueOcrBackend(["AC-3", "死地"]))
    chinese = _process(controller, _frame())
    english = controller.set_locale("en")

    assert chinese.session == english.session
    assert chinese.presentation.title == "本局情报"
    assert english.presentation.title == "Encounter Intel"
    payload = json.loads(controller.diagnostic_json())
    assert payload["build"] == LIVE_ENCOUNTER_PREVIEW_BUILD
    assert payload["capture_dimensions"] == [1920, 1080]
    assert payload["ocr_available"] is True
    assert payload["map_id"] is None
    assert payload["simulation_code"] == "AC-3"
    assert payload["observed_difficulty"] == "死地"
    assert "player" not in payload


def test_live_loop_stops_cleanly_after_one_frame() -> None:
    controller = LiveEncounterPreviewController(_QueueOcrBackend(["AC-3", "死地"]))
    snapshots: list[LiveEncounterPreviewSnapshot] = []
    run_live_encounter_loop(_Frames((_frame(),)), controller, snapshots.append)

    assert snapshots[-1].status is LiveEncounterPreviewStatus.STOPPED
    assert snapshots[0].presentation.progress_label == "0 / 4"


def test_existing_outside_run_debounce_ends_without_creating_or_resurrecting_an_encounter() -> None:
    controller = LiveEncounterPreviewController(_QueueOcrBackend(["AC-3", "死地"]))
    active = _process(controller, _frame())
    first = controller.apply_outside_run_observations((_outside(),))
    ended = controller.apply_outside_run_observations((_outside(),))
    after_operation = _process(controller, _frame(1))

    assert active.encounter_ended is False
    assert first.encounter_ended is False
    assert ended.encounter_ended is True
    assert ended.status is LiveEncounterPreviewStatus.ENDED_WAITING_NEXT
    assert ended.presentation.title == "上一局情报"
    assert ended.session == active.session
    assert after_operation.session == active.session
    assert after_operation.encounter_ended is True


def test_one_outside_frame_does_not_end_and_an_absence_resets_the_existing_debounce() -> None:
    controller = LiveEncounterPreviewController(_QueueOcrBackend(["AC-3", "死地"]))
    _process(controller, _frame())
    first = controller.apply_outside_run_observations((_outside(),))
    reset = controller.apply_outside_run_observations(())

    assert first.encounter_ended is False
    assert reset.encounter_ended is False


def test_live_controller_keeps_same_map_difficulty_conflict_visible() -> None:
    catalog = EncounterMapCatalog(
        definitions=(),
        difficulties=(
            DifficultyDefinition(
                difficulty_id="difficulty.synthetic.a",
                simulation_codes=("AC-3",),
                names=(LocalizedText(locale_id="zh_CN", text="A"),),
            ),
            DifficultyDefinition(
                difficulty_id="difficulty.synthetic.b",
                simulation_codes=("AC-4",),
                names=(LocalizedText(locale_id="zh_CN", text="B"),),
            ),
        ),
    )
    controller = LiveEncounterPreviewController(_QueueOcrBackend([]), catalog=catalog)
    observation = replace(
        _operation_observation("difficulty.synthetic.a", "A"),
        simulation_code="AC-3",
    )
    controller.apply_operation_observation(observation)
    conflict = controller.apply_operation_observation(
        replace(
            observation,
            simulation_code="AC-4",
            difficulty_id="difficulty.synthetic.b",
            observed_difficulty="B",
        )
    )

    assert conflict.status is EncounterUpdateStatus.CONFLICT
    assert controller.session.captured_map is None
    assert controller.session.captured_difficulty is not None
    assert controller.session.captured_difficulty.difficulty_id == "difficulty.synthetic.a"
    assert controller.session.difficulty_conflict is not None


def _operation_observation(
    difficulty_id: str,
    observed_difficulty: str,
) -> OperationDifficultyObservation:
    frame = _frame()
    observation = asyncio.run(
        observe_jp_mumu_operation_difficulty(
            frame,
            ContentViewport.full_frame(frame),
            _QueueOcrBackend(["AC-3", "死地"]),
        )
    )
    return replace(
        observation,
        difficulty_id=difficulty_id,
        observed_difficulty=observed_difficulty,
    )


def _outside() -> OutsideRunPageObservation:
    return OutsideRunPageObservation(
        page_kind=OutsideRunPageKind.SUCCESS_RESULT,
        state=OutsideRunPageState.PRESENT,
        method=OutsideRunPageObservationMethod.FIXED_LAYOUT_PIXEL_CUES,
        frame_id="synthetic-outside:0",
        frame_index=0,
        processed_at=datetime(2026, 8, 28, tzinfo=UTC),
        source_timestamp=None,
        source_type=FrameSourceType.WINDOWS_DISPLAY,
        source_id="synthetic-live",
        source_reference="synthetic-display",
        metrics=(),
    )
