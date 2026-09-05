from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime

import cv2
import numpy as np
import pytest

from sentry_copilot.capture.frame_source import (
    Frame,
    FrameSource,
    FrameSourceMetadata,
    FrameSourceType,
)
from sentry_copilot.capture.mumu_ipc import MuMuIpcCaptureError
from sentry_copilot.encounter.catalog import EncounterMapCatalog
from sentry_copilot.encounter.lifecycle import begin_encounter
from sentry_copilot.encounter.models import (
    MAJOR_COVENANT_IDS,
    BossDefinition,
    CapturedDifficulty,
    CovenantBanState,
    DifficultyCaptureSource,
    DifficultyDefinition,
    EnemyCategoryDefinition,
    LocalizedText,
    MajorCovenantBanSnapshot,
    MajorCovenantBanStateEntry,
)
from sentry_copilot.encounter.session import EncounterUpdateStatus
from sentry_copilot.services.live_encounter_preview import (
    INFO_REENTRY_CONFIRMATION_COUNT,
    LIVE_ENCOUNTER_PREVIEW_BUILD,
    LiveEncounterPreviewController,
    LiveEncounterPreviewSnapshot,
    LiveEncounterPreviewStatus,
    _asset_basename,
    _sanitize_reference_load_failure,
    _status_message,
    run_live_encounter_loop,
)
from sentry_copilot.vision.difficulty_recovery import (
    OPERATION_SPLASH_DIFFICULTY_ROI,
    POST_START_DIFFICULTY_ROI,
    DifficultyRecoveryReferencePack,
)
from sentry_copilot.vision.info_1_2 import (
    BOSS_ROI,
    ENEMY_SLOT_ROIS,
    INFO_1_2_ANCHOR_ROI,
    INFO_DIFFICULTY_IDS,
    INFO_DIFFICULTY_ROI,
    EnemySlotLayout,
    EnemyVisualReference,
    Info12Observation,
    Info12ReferencePack,
    Info12State,
    RankedVisualCandidate,
    VisualReference,
)
from sentry_copilot.vision.info_recovery_pages import (
    INFO_2_2_PHASE_LABEL_ROI,
    RETURNED_INFO_HEADER_ROI,
    InfoRecoveryPageObservation,
    InfoRecoveryPageReferencePack,
    InfoRecoveryPageState,
)
from sentry_copilot.vision.ocr import OcrBackendReading
from sentry_copilot.vision.operation_difficulty import (
    OperationDifficultyObservation,
    OperationDifficultyState,
    observe_jp_mumu_operation_difficulty,
)
from sentry_copilot.vision.outside_run_pages import (
    OutsideRunPageKind,
    OutsideRunPageObservation,
    OutsideRunPageObservationMethod,
    OutsideRunPageState,
)
from sentry_copilot.vision.returned_info_recovery import (
    RETURNED_INFO_BOSS_ROI,
    RETURNED_INFO_ENEMY_SLOT_ROIS,
)
from sentry_copilot.vision.viewport import ContentViewport


class _QueueOcrBackend:
    def __init__(self, readings: list[str | None]) -> None:
        self._readings = iter(readings)

    async def recognize(self, image: np.ndarray, *, language_tag: str) -> OcrBackendReading:
        del image
        assert language_tag == "ja-JP"
        return OcrBackendReading(next(self._readings))


class _FailingOcr:
    async def recognize(self, image: np.ndarray, *, language_tag: str) -> OcrBackendReading:
        del image, language_tag
        raise AssertionError("live INFO preview must not invoke OPERATION OCR")


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


def _info_references() -> Info12ReferencePack:
    anchor = np.zeros((INFO_1_2_ANCHOR_ROI.height, INFO_1_2_ANCHOR_ROI.width, 3), dtype=np.uint8)
    anchor[:, ::2] = 255
    boss = np.full((BOSS_ROI.height, BOSS_ROI.width, 3), 1, dtype=np.uint8)
    difficulty = np.full(
        (INFO_DIFFICULTY_ROI.height, INFO_DIFFICULTY_ROI.width, 3), 1, dtype=np.uint8
    )
    return Info12ReferencePack(
        anchor,
        tuple(VisualReference(f"boss.{index}", boss) for index in range(7)),
        tuple(
            EnemyVisualReference(f"enemy.{index}", _synthetic_enemy_reference(index))
            for index in range(7)
        ),
        tuple(VisualReference(identity_id, difficulty) for identity_id in INFO_DIFFICULTY_IDS),
    )


def _synthetic_enemy_reference(index: int) -> np.ndarray:
    """Make distinct alpha-retained shapes so a synthetic INFO frame has one reliable enemy."""

    image = np.zeros((ENEMY_SLOT_ROIS[0].height, ENEMY_SLOT_ROIS[0].width, 4), dtype=np.uint8)
    pattern = np.random.default_rng(index).integers(0, 2, (16, 16), dtype=np.uint8) * 255
    pattern[0, 0] = 255
    expanded = cv2.resize(pattern, (96, 96), interpolation=cv2.INTER_NEAREST)
    image[18:114, 18:114, :3] = expanded[:, :, None]
    image[18:114, 18:114, 3] = expanded
    return image


def _returned_info_recovery_references() -> Info12ReferencePack:
    anchor = np.zeros((INFO_1_2_ANCHOR_ROI.height, INFO_1_2_ANCHOR_ROI.width, 3), dtype=np.uint8)
    anchor[:, ::2] = 255
    bosses = tuple(
        VisualReference(
            f"boss.{index}",
            _returned_boss_image(
                index,
                width=RETURNED_INFO_BOSS_ROI.width,
                height=RETURNED_INFO_BOSS_ROI.height,
            ),
        )
        for index in range(7)
    )
    enemy = tuple(
        EnemyVisualReference(f"enemy.{index}", _returned_enemy_image(index)) for index in range(7)
    )
    return Info12ReferencePack(
        anchor,
        bosses,
        enemy,
    )


def _returned_info_catalog() -> EncounterMapCatalog:
    return EncounterMapCatalog(
        definitions=(),
        bosses=tuple(
            BossDefinition(
                boss_id=f"boss.{index}", names=(LocalizedText(locale_id="zh_CN", text=str(index)),)
            )
            for index in range(7)
        ),
        enemy_categories=tuple(
            EnemyCategoryDefinition(
                enemy_category_id=f"enemy.{index}",
                names=(LocalizedText(locale_id="zh_CN", text=str(index)),),
            )
            for index in range(7)
        ),
        difficulties=(
            DifficultyDefinition(
                difficulty_id="difficulty.synthetic",
                simulation_codes=("AC-1",),
                names=(LocalizedText(locale_id="zh_CN", text="Synthetic"),),
            ),
        ),
    )


def _recovery_image(index: int, *, width: int, height: int) -> np.ndarray:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :: index + 2] = 35 + index * 65
    image[8 + index * 4 : 40 + index * 7, 12 + index * 9 : 85 + index * 12] = (
        255,
        255 - index * 45,
        75 + index * 45,
    )
    return image


def _returned_boss_image(index: int, *, width: int, height: int) -> np.ndarray:
    return np.random.default_rng(index).integers(0, 256, size=(height, width, 3), dtype=np.uint8)


def _returned_enemy_image(index: int) -> np.ndarray:
    image = np.zeros((132, 132, 4), dtype=np.uint8)
    pattern = np.random.default_rng(index).integers(0, 2, (16, 16), dtype=np.uint8) * 255
    pattern[0, 0] = 255
    expanded = cv2.resize(pattern, (96, 96), interpolation=cv2.INTER_NEAREST)
    image[20:116, 18:114, :3] = expanded[:, :, None]
    image[20:116, 18:114, 3] = expanded
    return image


def _recovery_references() -> DifficultyRecoveryReferencePack:
    post_templates = tuple(
        VisualReference(
            identity_id,
            _recovery_image(
                index,
                width=POST_START_DIFFICULTY_ROI.width,
                height=POST_START_DIFFICULTY_ROI.height,
            ),
        )
        for index, identity_id in enumerate(INFO_DIFFICULTY_IDS)
    )
    operation_templates = tuple(
        VisualReference(
            identity_id,
            _recovery_image(
                index,
                width=OPERATION_SPLASH_DIFFICULTY_ROI.width,
                height=OPERATION_SPLASH_DIFFICULTY_ROI.height,
            ),
        )
        for index, identity_id in enumerate(INFO_DIFFICULTY_IDS)
    )
    return DifficultyRecoveryReferencePack(post_templates, operation_templates)


def _recovery_page_references() -> InfoRecoveryPageReferencePack:
    phase = np.zeros(
        (INFO_2_2_PHASE_LABEL_ROI.height, INFO_2_2_PHASE_LABEL_ROI.width, 3), dtype=np.uint8
    )
    phase[:, ::3] = (180, 90, 40)
    returned = np.zeros(
        (RETURNED_INFO_HEADER_ROI.height, RETURNED_INFO_HEADER_ROI.width, 3), dtype=np.uint8
    )
    returned[::3, :] = (40, 180, 90)
    return InfoRecoveryPageReferencePack(phase, returned)


def _recovery_page_frame(index: int, *, phase: bool = False, returned: bool = False) -> Frame:
    frame = _frame(index)
    image = np.array(frame.image, copy=True)
    references = _recovery_page_references()
    if phase:
        image[
            INFO_2_2_PHASE_LABEL_ROI.y : INFO_2_2_PHASE_LABEL_ROI.bottom,
            INFO_2_2_PHASE_LABEL_ROI.x : INFO_2_2_PHASE_LABEL_ROI.right,
        ] = references.phase_2_2_label
    if returned:
        image[
            RETURNED_INFO_HEADER_ROI.y : RETURNED_INFO_HEADER_ROI.bottom,
            RETURNED_INFO_HEADER_ROI.x : RETURNED_INFO_HEADER_ROI.right,
        ] = references.returned_info_header
    return replace(frame, image=image)


def _returned_info_boss_frame(index: int, *, returned: bool) -> Frame:
    frame = _recovery_page_frame(index, returned=returned)
    image = np.array(frame.image, copy=True)
    boss = _returned_info_recovery_references().bosses[0].image
    image[
        RETURNED_INFO_BOSS_ROI.y : RETURNED_INFO_BOSS_ROI.bottom,
        RETURNED_INFO_BOSS_ROI.x : RETURNED_INFO_BOSS_ROI.right,
    ] = boss
    return replace(frame, image=image)


def _returned_info_enemy_frame(index: int, *, returned: bool, ids: tuple[int, ...]) -> Frame:
    frame = _recovery_page_frame(index, returned=returned)
    image = np.array(frame.image, copy=True)
    references = _returned_info_recovery_references()
    for enemy_id, roi in zip(ids, RETURNED_INFO_ENEMY_SLOT_ROIS[: len(ids)], strict=True):
        image[roi.y : roi.bottom, roi.x : roi.right] = cv2.resize(
            references.enemy_categories[enemy_id].image[:, :, :3],
            (roi.width, roi.height),
            interpolation=cv2.INTER_NEAREST,
        )
    return replace(frame, image=image)


def _recovery_frame(index: int, *, source: str, difficulty_index: int | None) -> Frame:
    frame = _frame(index)
    image = np.array(frame.image, copy=True)
    if difficulty_index is not None:
        roi = POST_START_DIFFICULTY_ROI if source == "post" else OPERATION_SPLASH_DIFFICULTY_ROI
        template = (
            _recovery_references().post_start_templates[difficulty_index].image
            if source == "post"
            else _recovery_references().operation_splash_templates[difficulty_index].image
        )
        image[roi.y : roi.bottom, roi.x : roi.right] = template
    return replace(frame, image=image)


def _post_start_phase_frame(index: int, *, difficulty_index: int | None) -> Frame:
    frame = _recovery_page_frame(index, phase=True)
    image = np.array(frame.image, copy=True)
    if difficulty_index is not None:
        image[
            POST_START_DIFFICULTY_ROI.y : POST_START_DIFFICULTY_ROI.bottom,
            POST_START_DIFFICULTY_ROI.x : POST_START_DIFFICULTY_ROI.right,
        ] = _recovery_references().post_start_templates[difficulty_index].image
    return replace(frame, image=image)


def _arm_for_difficulty_recovery(controller: LiveEncounterPreviewController) -> None:
    controller.apply_info_1_2_observation(_info_observation(Info12State.PRESENT))
    for _ in range(3):
        controller.apply_info_1_2_observation(_info_observation(Info12State.ABSENT))
    assert controller._info_lifecycle_state.value == "armed_for_next_info"  # noqa: SLF001


def _set_recovery_page_states(
    controller: LiveEncounterPreviewController,
    frame_id: str,
    *,
    phase: InfoRecoveryPageState,
    returned: InfoRecoveryPageState = InfoRecoveryPageState.ABSENT,
) -> None:
    controller._latest_info_2_2_phase = InfoRecoveryPageObservation(  # noqa: SLF001
        phase, frame_id, 0.99 if phase is InfoRecoveryPageState.PRESENT else 0.01
    )
    controller._latest_returned_info = InfoRecoveryPageObservation(  # noqa: SLF001
        returned, frame_id, 0.99 if returned is InfoRecoveryPageState.PRESENT else 0.01
    )


def _info_frame(index: int = 0) -> Frame:
    frame = _frame(index)
    image = np.array(frame.image, copy=True)
    image[
        INFO_1_2_ANCHOR_ROI.y : INFO_1_2_ANCHOR_ROI.bottom,
        INFO_1_2_ANCHOR_ROI.x : INFO_1_2_ANCHOR_ROI.right,
    ] = _info_references().anchor
    first_enemy = _info_references().enemy_categories[0].image[:, :, :3]
    first_enemy_roi = ENEMY_SLOT_ROIS[0]
    image[
        first_enemy_roi.y : first_enemy_roi.bottom,
        first_enemy_roi.x : first_enemy_roi.right,
    ] = first_enemy
    return replace(frame, image=image)


def _mumu_frame(index: int = 0, *, size: tuple[int, int] = (1920, 1080)) -> Frame:
    return replace(
        _frame(index, size=size),
        source_type=FrameSourceType.MUMU_IPC,
        source_id="mumu-ipc:instance-0:display-0",
        source_reference="mumu-renderer-ipc:instance=0,display=0",
    )


def _mumu_info_frame(index: int = 0) -> Frame:
    frame = _mumu_frame(index)
    image = np.array(frame.image, copy=True)
    image[
        INFO_1_2_ANCHOR_ROI.y : INFO_1_2_ANCHOR_ROI.bottom,
        INFO_1_2_ANCHOR_ROI.x : INFO_1_2_ANCHOR_ROI.right,
    ] = _info_references().anchor
    first_enemy = _info_references().enemy_categories[0].image[:, :, :3]
    first_enemy_roi = ENEMY_SLOT_ROIS[0]
    image[
        first_enemy_roi.y : first_enemy_roi.bottom,
        first_enemy_roi.x : first_enemy_roi.right,
    ] = first_enemy
    return replace(frame, image=image)


def _process(
    controller: LiveEncounterPreviewController, frame: Frame
) -> LiveEncounterPreviewSnapshot:
    return asyncio.run(controller.process_frame(frame))


def _active(controller: LiveEncounterPreviewController) -> LiveEncounterPreviewController:
    """Explicit test-only established-start fixture; OPERATION never starts a session."""
    controller._session = begin_encounter("test:started")  # noqa: SLF001
    return controller


def _info_observation(
    state: Info12State,
    *,
    difficulty_id: str | None = None,
    boss_id: str | None = None,
    reliable_enemy: bool = True,
) -> Info12Observation:
    ranking = (
        (
            RankedVisualCandidate(difficulty_id, 0.99),
            RankedVisualCandidate("difficulty.other", 0.01),
        )
        if difficulty_id is not None
        else ()
    )
    boss_ranking = (
        (
            RankedVisualCandidate(boss_id, 0.99),
            RankedVisualCandidate("boss.other", 0.01),
        )
        if boss_id is not None
        else ()
    )
    enemy_rankings = (
        (
            (
                RankedVisualCandidate("enemy.synthetic", 0.99),
                RankedVisualCandidate("enemy.other", 0.01),
            ),
            (),
        )
        if state is Info12State.PRESENT and reliable_enemy
        else ()
    )
    return Info12Observation(
        state=state,
        frame_id=f"synthetic-info:{state.value}",
        anchor_score=0.99 if state is Info12State.PRESENT else 0.01,
        difficulty_ranking=ranking,
        boss_ranking=boss_ranking,
        enemy_rankings=enemy_rankings,
        enemy_slot_layout=(
            EnemySlotLayout.TWO_SLOT if enemy_rankings else EnemySlotLayout.UNRESOLVED
        ),
    )


def _strict_next_info_observation(
    index: int,
    *,
    difficulty_id: str = "difficulty.covenant_latter.deadland",
) -> Info12Observation:
    ranking = (
        RankedVisualCandidate(difficulty_id, 0.99),
        RankedVisualCandidate("difficulty.other", 0.01),
    )
    return Info12Observation(
        state=Info12State.PRESENT,
        frame_id=f"synthetic-strict-next:{index}",
        anchor_score=0.99,
        enemy_rankings=(
            (
                RankedVisualCandidate("enemy.synthetic", 0.99),
                RankedVisualCandidate("enemy.other", 0.01),
            ),
            (),
        ),
        enemy_slot_layout=EnemySlotLayout.TWO_SLOT,
        difficulty_ranking=ranking,
    )


def _generic_present_observation(index: int) -> Info12Observation:
    return Info12Observation(
        state=Info12State.PRESENT,
        frame_id=f"synthetic-generic-present:{index}",
        anchor_score=0.99,
        enemy_rankings=((), ()),
        enemy_slot_layout=EnemySlotLayout.TWO_SLOT,
    )


def _structured_present_without_enemy(
    index: int,
    *,
    difficulty_id: str | None = None,
    boss_id: str | None = None,
) -> Info12Observation:
    """Model a wrong INFO-anchor page with canonical slot structure but no enemy identity."""

    difficulty_ranking = (
        (
            RankedVisualCandidate(difficulty_id, 0.99),
            RankedVisualCandidate("difficulty.other", 0.01),
        )
        if difficulty_id is not None
        else ()
    )
    boss_ranking = (
        (
            RankedVisualCandidate(boss_id, 0.99),
            RankedVisualCandidate("boss.other", 0.01),
        )
        if boss_id is not None
        else ()
    )
    return Info12Observation(
        state=Info12State.PRESENT,
        frame_id=f"synthetic-structured-without-enemy:{index}",
        anchor_score=0.99,
        boss_ranking=boss_ranking,
        enemy_rankings=((), ()),
        enemy_slot_layout=EnemySlotLayout.TWO_SLOT,
        difficulty_ranking=difficulty_ranking,
    )


def _complete_major_ban_snapshot() -> MajorCovenantBanSnapshot:
    covenant_ids = tuple(sorted(MAJOR_COVENANT_IDS))
    disabled = frozenset(covenant_ids[-3:])
    return MajorCovenantBanSnapshot(
        covenant_states=tuple(
            MajorCovenantBanStateEntry(
                covenant_id=covenant_id,
                state=(
                    CovenantBanState.DISABLED
                    if covenant_id in disabled
                    else CovenantBanState.UNRESTRICTED
                ),
            )
            for covenant_id in covenant_ids
        )
    )


def test_live_controller_starts_empty_and_has_no_manual_new_encounter_api() -> None:
    controller = LiveEncounterPreviewController(
        _QueueOcrBackend([]), info_1_2_references=_info_references()
    )

    initial = controller.snapshot()
    assert initial.presentation.progress_label == "0 / 5"
    assert initial.status is LiveEncounterPreviewStatus.WAITING_FOR_SUPPORTED_FRAME
    assert initial.presentation.items[1].implemented is True
    assert initial.presentation.items[1].value == "尚未识别"
    assert not hasattr(controller, "new_encounter")
    diagnostic = json.loads(controller.diagnostic_json())
    assert diagnostic["encounter_id"] is None
    assert diagnostic["info_lifecycle_state"] == "waiting_for_initial_info"
    assert diagnostic["info_departure_count"] == 0
    assert diagnostic["info_reentry_count"] == 0

    replacement_process = LiveEncounterPreviewController(
        _QueueOcrBackend([]), info_1_2_references=_info_references()
    )
    assert replacement_process.session is None
    assert initial.session is None
    assert replacement_process.snapshot().presentation.progress_label == "0 / 5"


def test_live_controller_uses_info_visual_recognition_without_operation_ocr() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(), info_1_2_references=_info_references()
    )

    unsupported = _process(controller, _frame(size=(1280, 720)))
    assert unsupported.status is LiveEncounterPreviewStatus.WAITING_FOR_SUPPORTED_FRAME
    assert unsupported.presentation.progress_label == "0 / 5"

    initial = _process(controller, _info_frame(1))
    assert initial.presentation.progress_label == "0 / 5"
    assert initial.latest_map_id is None
    assert initial.latest_difficulty_id is None
    assert initial.status is LiveEncounterPreviewStatus.RUNNING


def test_post_start_visual_fills_only_a_missing_difficulty_after_info_is_absent() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(),
        info_1_2_references=_info_references(),
        difficulty_recovery_references=_recovery_references(),
        info_recovery_page_references=_recovery_page_references(),
    )
    controller.apply_info_1_2_observation(_info_observation(Info12State.PRESENT))

    before_departure = _process(controller, _recovery_frame(10, source="post", difficulty_index=0))
    still_before_departure = _process(
        controller, _recovery_frame(11, source="post", difficulty_index=0)
    )
    assert before_departure.latest_difficulty_id is None
    assert still_before_departure.latest_difficulty_id is None

    _process(controller, _recovery_frame(12, source="post", difficulty_index=None))
    first = _process(controller, _post_start_phase_frame(13, difficulty_index=0))
    captured = _process(controller, _post_start_phase_frame(14, difficulty_index=0))

    assert first.latest_difficulty_id is None
    assert captured.latest_difficulty_id == INFO_DIFFICULTY_IDS[0]
    assert controller.session is not None
    assert controller.session.captured_difficulty is not None
    assert (
        controller.session.captured_difficulty.capture_source
        is DifficultyCaptureSource.POST_START_VISUAL
    )


@pytest.mark.parametrize(
    "phase_state",
    (InfoRecoveryPageState.ABSENT, InfoRecoveryPageState.UNRESOLVED),
)
def test_post_start_difficulty_requires_current_semantic_info_2_2(
    phase_state: InfoRecoveryPageState,
) -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(),
        info_1_2_references=_info_references(),
        difficulty_recovery_references=_recovery_references(),
    )
    _arm_for_difficulty_recovery(controller)
    frame = _recovery_frame(40, source="post", difficulty_index=0)
    _set_recovery_page_states(controller, frame.frame_id, phase=phase_state)

    controller._observe_missing_difficulty_recovery(  # noqa: SLF001
        frame,
        ContentViewport.full_frame(frame),
        Info12Observation(Info12State.ABSENT, frame.frame_id, 0.01),
    )

    assert controller.session is not None
    assert controller.session.captured_difficulty is None
    assert controller._latest_post_start_difficulty is None  # noqa: SLF001
    assert controller._post_start_difficulty_pending_count == 0  # noqa: SLF001


def test_post_start_difficulty_requires_same_frame_info_2_2_and_resets_interrupted_streak() -> (
    None
):
    controller = LiveEncounterPreviewController(
        _FailingOcr(),
        info_1_2_references=_info_references(),
        difficulty_recovery_references=_recovery_references(),
    )
    _arm_for_difficulty_recovery(controller)
    first = _recovery_frame(41, source="post", difficulty_index=0)
    _set_recovery_page_states(controller, first.frame_id, phase=InfoRecoveryPageState.PRESENT)
    controller._observe_missing_difficulty_recovery(  # noqa: SLF001
        first,
        ContentViewport.full_frame(first),
        Info12Observation(Info12State.ABSENT, first.frame_id, 0.01),
    )
    assert controller._post_start_difficulty_pending_count == 1  # noqa: SLF001

    interrupted = _recovery_frame(42, source="post", difficulty_index=0)
    _set_recovery_page_states(
        controller, interrupted.frame_id, phase=InfoRecoveryPageState.ABSENT
    )
    controller._observe_missing_difficulty_recovery(  # noqa: SLF001
        interrupted,
        ContentViewport.full_frame(interrupted),
        Info12Observation(Info12State.ABSENT, interrupted.frame_id, 0.01),
    )
    assert controller._post_start_difficulty_pending_count == 0  # noqa: SLF001

    second = _recovery_frame(43, source="post", difficulty_index=0)
    _set_recovery_page_states(controller, second.frame_id, phase=InfoRecoveryPageState.PRESENT)
    controller._observe_missing_difficulty_recovery(  # noqa: SLF001
        second,
        ContentViewport.full_frame(second),
        Info12Observation(Info12State.ABSENT, second.frame_id, 0.01),
    )
    assert controller.session is not None
    assert controller.session.captured_difficulty is None
    assert controller._post_start_difficulty_pending_count == 1  # noqa: SLF001

    final = _recovery_frame(44, source="post", difficulty_index=0)
    _set_recovery_page_states(controller, final.frame_id, phase=InfoRecoveryPageState.PRESENT)
    controller._observe_missing_difficulty_recovery(  # noqa: SLF001
        final,
        ContentViewport.full_frame(final),
        Info12Observation(Info12State.ABSENT, final.frame_id, 0.01),
    )
    assert controller.session is not None
    assert controller.session.captured_difficulty is not None


def test_stale_or_returned_info_2_2_evidence_does_not_authorize_post_start_difficulty() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(),
        info_1_2_references=_info_references(),
        difficulty_recovery_references=_recovery_references(),
    )
    _arm_for_difficulty_recovery(controller)
    frame = _recovery_frame(45, source="post", difficulty_index=0)
    _set_recovery_page_states(controller, "stale-phase", phase=InfoRecoveryPageState.PRESENT)
    controller._observe_missing_difficulty_recovery(  # noqa: SLF001
        frame,
        ContentViewport.full_frame(frame),
        Info12Observation(Info12State.ABSENT, frame.frame_id, 0.01),
    )
    assert controller._latest_post_start_difficulty is None  # noqa: SLF001

    _set_recovery_page_states(
        controller,
        frame.frame_id,
        phase=InfoRecoveryPageState.PRESENT,
        returned=InfoRecoveryPageState.PRESENT,
    )
    controller._observe_missing_difficulty_recovery(  # noqa: SLF001
        frame,
        ContentViewport.full_frame(frame),
        Info12Observation(Info12State.ABSENT, frame.frame_id, 0.01),
    )
    assert controller._latest_post_start_difficulty is None  # noqa: SLF001
    assert controller._post_start_difficulty_pending_count == 0  # noqa: SLF001


def test_operation_difficulty_recovery_remains_independent_of_info_2_2() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(),
        info_1_2_references=_info_references(),
        difficulty_recovery_references=_recovery_references(),
    )
    _arm_for_difficulty_recovery(controller)
    for index in (46, 47):
        frame = _recovery_frame(index, source="operation", difficulty_index=2)
        _set_recovery_page_states(controller, frame.frame_id, phase=InfoRecoveryPageState.ABSENT)
        controller._observe_missing_difficulty_recovery(  # noqa: SLF001
            frame,
            ContentViewport.full_frame(frame),
            Info12Observation(Info12State.ABSENT, frame.frame_id, 0.01),
        )

    assert controller.session is not None
    assert controller.session.captured_difficulty is not None
    assert (
        controller.session.captured_difficulty.capture_source
        is DifficultyCaptureSource.OPERATION_SPLASH_VISUAL
    )


def test_visual_difficulty_fallback_never_starts_an_encounter() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(),
        info_1_2_references=_info_references(),
        difficulty_recovery_references=_recovery_references(),
    )

    _process(controller, _recovery_frame(12, source="post", difficulty_index=0))
    snapshot = _process(controller, _recovery_frame(13, source="post", difficulty_index=0))

    assert controller.session is None
    assert snapshot.latest_difficulty_id is None


def test_fallback_is_not_applied_when_the_genuine_info_state_is_unresolved() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(),
        info_1_2_references=_info_references(),
        difficulty_recovery_references=_recovery_references(),
    )
    controller.apply_info_1_2_observation(_info_observation(Info12State.PRESENT))
    for index in range(16, 19):
        _process(controller, _recovery_frame(index, source="post", difficulty_index=None))
    frame = _recovery_frame(15, source="post", difficulty_index=0)

    controller._observe_missing_difficulty_recovery(  # noqa: SLF001
        frame,
        ContentViewport.full_frame(frame),
        _info_observation(Info12State.UNRESOLVED),
    )

    assert controller.session is not None
    assert controller.session.captured_difficulty is None


def test_operation_splash_visual_fills_missing_difficulty_and_unreliable_frame_breaks_streak(
) -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(),
        info_1_2_references=_info_references(),
        difficulty_recovery_references=_recovery_references(),
    )
    controller.apply_info_1_2_observation(_info_observation(Info12State.PRESENT))

    before_departure = _process(
        controller, _recovery_frame(20, source="operation", difficulty_index=2)
    )
    still_before_departure = _process(
        controller, _recovery_frame(21, source="operation", difficulty_index=2)
    )
    assert before_departure.latest_difficulty_id is None
    assert still_before_departure.latest_difficulty_id is None

    _process(controller, _recovery_frame(22, source="operation", difficulty_index=None))
    _process(controller, _recovery_frame(23, source="operation", difficulty_index=2))
    _process(controller, _recovery_frame(24, source="operation", difficulty_index=None))
    after_restart = _process(
        controller, _recovery_frame(25, source="operation", difficulty_index=2)
    )
    assert after_restart.latest_difficulty_id is None

    captured = _process(controller, _recovery_frame(26, source="operation", difficulty_index=2))
    assert captured.latest_difficulty_id == INFO_DIFFICULTY_IDS[2]
    assert controller.session is not None
    assert controller.session.captured_difficulty is not None
    assert (
        controller.session.captured_difficulty.capture_source
        is DifficultyCaptureSource.OPERATION_SPLASH_VISUAL
    )


def test_fallback_is_skipped_for_captured_difficulty_and_genuine_info_reentry() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(),
        info_1_2_references=_info_references(),
        difficulty_recovery_references=_recovery_references(),
    )
    difficulty_info = _info_observation(
        Info12State.PRESENT, difficulty_id=INFO_DIFFICULTY_IDS[1]
    )
    controller.apply_info_1_2_observation(difficulty_info)
    controller.apply_info_1_2_observation(difficulty_info)
    assert controller.session is not None
    assert controller.session.captured_difficulty is not None

    _process(controller, _recovery_frame(30, source="post", difficulty_index=0))
    assert controller.session.captured_difficulty.difficulty_id == INFO_DIFFICULTY_IDS[1]

    missing = LiveEncounterPreviewController(
        _FailingOcr(),
        info_1_2_references=_info_references(),
        difficulty_recovery_references=_recovery_references(),
    )
    missing.apply_info_1_2_observation(_info_observation(Info12State.PRESENT))
    for _ in range(3):
        missing.apply_info_1_2_observation(_info_observation(Info12State.ABSENT))
    first_next_info = _frame(31)
    image = np.array(first_next_info.image, copy=True)
    image[
        INFO_1_2_ANCHOR_ROI.y : INFO_1_2_ANCHOR_ROI.bottom,
        INFO_1_2_ANCHOR_ROI.x : INFO_1_2_ANCHOR_ROI.right,
    ] = _info_references().anchor
    image[
        POST_START_DIFFICULTY_ROI.y : POST_START_DIFFICULTY_ROI.bottom,
        POST_START_DIFFICULTY_ROI.x : POST_START_DIFFICULTY_ROI.right,
    ] = _recovery_references().post_start_templates[0].image
    _process(missing, replace(first_next_info, image=image))

    assert missing.session is not None
    assert missing.session.encounter_id == "live-encounter:1"
    assert missing.session.captured_difficulty is None
    for index in range(32, 34):
        missing.apply_info_1_2_observation(_strict_next_info_observation(index))
        assert missing.session is not None
        assert missing.session.encounter_id == "live-encounter:1"
    missing.apply_info_1_2_observation(_strict_next_info_observation(34))
    assert missing.session is not None
    assert missing.session.encounter_id == "live-encounter:2"


def test_first_genuine_info_starts_encounter_one() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(), info_1_2_references=_info_references()
    )

    controller.apply_info_1_2_observation(_info_observation(Info12State.PRESENT))

    assert controller.session is not None
    assert controller.session.encounter_id == "live-encounter:1"
    assert controller._info_lifecycle_state.value == "initial_info"  # noqa: SLF001
    diagnostic = json.loads(controller.diagnostic_json())
    assert diagnostic["encounter_id"] == "live-encounter:1"
    assert diagnostic["info_lifecycle_state"] == "initial_info"


@pytest.mark.parametrize(
    ("difficulty_id", "boss_id"),
    (
        ("difficulty.covenant_latter.deadland", None),
        (None, "boss.0"),
    ),
)
def test_first_start_requires_a_reliable_enemy_not_only_difficulty_or_boss(
    difficulty_id: str | None,
    boss_id: str | None,
) -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(), info_1_2_references=_info_references()
    )

    controller.apply_info_1_2_observation(
        _info_observation(
            Info12State.PRESENT,
            difficulty_id=difficulty_id,
            boss_id=boss_id,
            reliable_enemy=False,
        )
    )

    assert controller.session is None


def test_initial_info_fact_application_requires_a_reliable_enemy() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(),
        catalog=_returned_info_catalog(),
        info_1_2_references=_info_references(),
    )
    controller.apply_info_1_2_observation(_info_observation(Info12State.PRESENT))
    assert controller.session is not None

    wrong_page = _info_observation(
        Info12State.PRESENT,
        difficulty_id="difficulty.synthetic",
        boss_id="boss.0",
        reliable_enemy=False,
    )
    for _ in range(3):
        controller.apply_info_1_2_observation(wrong_page)

    assert controller.session.captured_difficulty is None
    assert controller.session.boss_id is None


def test_info_flicker_does_not_create_a_second_encounter() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(), info_1_2_references=_info_references()
    )

    for state in (
        Info12State.PRESENT,
        Info12State.PRESENT,
        Info12State.ABSENT,
        Info12State.PRESENT,
        Info12State.PRESENT,
    ):
        controller.apply_info_1_2_observation(_info_observation(state))

    assert controller.session is not None
    assert controller.session.encounter_id == "live-encounter:1"
    assert controller._info_lifecycle_state.value == "initial_info"  # noqa: SLF001


def test_three_confirmed_info_absences_arm_replacement_without_ending_the_encounter() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(), info_1_2_references=_info_references()
    )
    controller.apply_info_1_2_observation(_info_observation(Info12State.PRESENT))
    first = controller.session

    for _ in range(3):
        controller.apply_info_1_2_observation(_info_observation(Info12State.ABSENT))

    assert controller.session == first
    assert controller.snapshot().encounter_ended is False
    assert controller._info_lifecycle_state.value == "armed_for_next_info"  # noqa: SLF001
    diagnostic = json.loads(controller.diagnostic_json())
    assert diagnostic["encounter_id"] == "live-encounter:1"
    assert diagnostic["info_lifecycle_state"] == "armed_for_next_info"
    assert diagnostic["info_departure_count"] == 3
    assert diagnostic["info_reentry_count"] == 0


def test_recovery_reminder_opens_only_after_departure_and_is_sticky_across_phase_misses() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(),
        info_1_2_references=_info_references(),
        info_recovery_page_references=_recovery_page_references(),
    )
    controller.apply_info_1_2_observation(_info_observation(Info12State.PRESENT))

    first = _process(controller, _recovery_page_frame(40, phase=True))
    second = _process(controller, _recovery_page_frame(41, phase=True))
    assert first.recovery_reminder_visible is False
    assert second.recovery_reminder_visible is False
    assert second.recovery_state == "inactive"

    armed = _process(controller, _recovery_page_frame(42, phase=True))
    shown = _process(controller, _recovery_page_frame(43, phase=True))
    assert armed.recovery_state == "open"
    assert armed.recovery_reminder_visible is False
    assert shown.recovery_reminder_visible is True
    assert shown.missing_recoverable_items == ("boss", "enemy_types")
    assert "情報確認" in (shown.recovery_reminder_text or "")

    missed = _process(controller, _recovery_page_frame(44))
    assert missed.recovery_reminder_visible is True
    assert json.loads(controller.diagnostic_json())["info_2_2_phase_present_streak"] == 0


def test_returned_info_hides_the_reminder_without_changing_recovery_state() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(),
        info_1_2_references=_info_references(),
        info_recovery_page_references=_recovery_page_references(),
    )
    controller.apply_info_1_2_observation(_info_observation(Info12State.PRESENT))
    for index in range(50, 53):
        _process(controller, _recovery_page_frame(index, phase=True))
    shown = _process(controller, _recovery_page_frame(53, phase=True))
    session = controller.session
    returned = _process(controller, _recovery_page_frame(54, returned=True))

    assert shown.recovery_reminder_visible is True
    assert returned.recovery_reminder_visible is False
    assert returned.recovery_state == "open"
    assert controller.session == session

    _process(controller, _recovery_page_frame(55, phase=True))
    reappeared = _process(controller, _recovery_page_frame(56, phase=True))
    assert reappeared.recovery_reminder_visible is True


def test_complete_boss_and_enemy_types_never_trigger_recovery_reminder() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(),
        info_1_2_references=_info_references(),
        info_recovery_page_references=_recovery_page_references(),
    )
    controller.apply_info_1_2_observation(_info_observation(Info12State.PRESENT))
    assert controller.session is not None
    controller._session = controller.session.model_copy(  # noqa: SLF001
        update={"boss_id": "boss.complete", "enemy_type_ids": ("enemy.a", "enemy.b")}
    )

    for index in range(60, 64):
        snapshot = _process(controller, _recovery_page_frame(index, phase=True))

    assert snapshot.recovery_state == "open"
    assert snapshot.recovery_reminder_visible is False
    assert snapshot.missing_recoverable_items == ()


def test_reliable_operation_closes_recovery_without_ending_or_replacing_the_encounter() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(),
        info_1_2_references=_info_references(),
        info_recovery_page_references=_recovery_page_references(),
    )
    controller.apply_info_1_2_observation(_info_observation(Info12State.PRESENT))
    for index in range(70, 74):
        shown = _process(controller, _recovery_page_frame(index, phase=True))
    session = controller.session

    controller.apply_operation_observation(
        _operation_observation("difficulty.synthetic", "Synthetic")
    )
    closed = controller.snapshot()

    assert shown.recovery_reminder_visible is True
    assert closed.recovery_state == "closed_for_run"
    assert closed.recovery_reminder_visible is False
    assert closed.session == session
    assert closed.encounter_ended is False


def test_phase_and_returned_info_observers_never_start_or_replace_an_encounter() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(),
        info_1_2_references=_info_references(),
        info_recovery_page_references=_recovery_page_references(),
    )

    phase = _process(controller, _recovery_page_frame(80, phase=True))
    returned = _process(controller, _recovery_page_frame(81, returned=True))

    assert phase.session is None
    assert returned.session is None
    assert returned.encounter_ended is False


def test_returned_info_boss_recovery_does_nothing_without_an_existing_encounter() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(),
        catalog=_returned_info_catalog(),
        info_1_2_references=_returned_info_recovery_references(),
        info_recovery_page_references=_recovery_page_references(),
    )

    snapshot = _process(controller, _returned_info_boss_frame(90, returned=True))

    assert snapshot.session is None
    assert snapshot.encounter_ended is False
    assert json.loads(controller.diagnostic_json())["returned_info_boss_state"] is None


def test_returned_info_boss_recovery_requires_returned_page_and_fills_only_missing_boss() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(),
        catalog=_returned_info_catalog(),
        info_1_2_references=_returned_info_recovery_references(),
        info_recovery_page_references=_recovery_page_references(),
    )
    controller.apply_info_1_2_observation(_info_observation(Info12State.PRESENT))
    for index in range(91, 94):
        outside_returned = _process(controller, _returned_info_boss_frame(index, returned=False))
    assert outside_returned.session is not None
    assert outside_returned.session.boss_id is None
    assert outside_returned.session.enemy_type_ids is None

    first = _process(controller, _returned_info_boss_frame(94, returned=True))
    captured = _process(controller, _returned_info_boss_frame(95, returned=True))

    assert first.session is not None and first.session.boss_id is None
    assert captured.session is not None
    assert captured.session.boss_id == "boss.0"
    assert captured.session.boss_capture_source is not None
    assert captured.session.boss_capture_source.value == "returned_info_visual"
    diagnostic = json.loads(controller.diagnostic_json())
    assert diagnostic["returned_info_boss_reliable_id"] == "boss.0"
    assert diagnostic["boss_capture_source"] == "returned_info_visual"


def test_returned_info_boss_recovery_preserves_existing_boss_and_difficulty() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(),
        catalog=_returned_info_catalog(),
        info_1_2_references=_returned_info_recovery_references(),
        info_recovery_page_references=_recovery_page_references(),
    )
    controller.apply_info_1_2_observation(_info_observation(Info12State.PRESENT))
    assert controller.session is not None
    controller._session = controller.session.model_copy(  # noqa: SLF001
        update={
            "boss_id": "boss.1",
            "captured_difficulty": CapturedDifficulty(
                difficulty_id="difficulty.synthetic",
                simulation_code="AC-1",
            ),
            "enemy_type_ids": ("enemy.0", "enemy.1"),
        }
    )
    for index in range(96, 100):
        preserved = _process(controller, _returned_info_boss_frame(index, returned=True))

    assert preserved.session is not None
    assert preserved.session.boss_id == "boss.1"
    assert preserved.session.boss_conflict is None
    assert preserved.session.captured_difficulty is not None
    assert preserved.session.captured_difficulty.difficulty_id == "difficulty.synthetic"
    assert preserved.session.enemy_type_ids == ("enemy.0", "enemy.1")


def test_returned_enemy_confirmation_is_independent_of_already_captured_boss() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(),
        catalog=_returned_info_catalog(),
        info_1_2_references=_returned_info_recovery_references(),
        info_recovery_page_references=_recovery_page_references(),
    )
    controller.apply_info_1_2_observation(_info_observation(Info12State.PRESENT))
    assert controller.session is not None
    controller._session = controller.session.model_copy(update={"boss_id": "boss.0"})  # noqa: SLF001
    for index in range(180, 183):
        _process(controller, _recovery_page_frame(index))

    first = _process(controller, _returned_info_enemy_frame(183, returned=True, ids=(0, 1)))
    captured = _process(controller, _returned_info_enemy_frame(184, returned=True, ids=(0, 1)))

    assert first.session is not None and first.session.enemy_type_ids is None
    assert captured.session is not None
    assert captured.session.enemy_type_ids == ("enemy.0", "enemy.1")
    assert captured.session.enemy_type_capture_source is not None
    assert captured.session.enemy_type_capture_source.value == "returned_info_visual"


def test_partial_returned_recovery_leaves_enemy_missing_so_2_2_reminder_returns() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(),
        catalog=_returned_info_catalog(),
        info_1_2_references=_returned_info_recovery_references(),
        info_recovery_page_references=_recovery_page_references(),
    )
    controller.apply_info_1_2_observation(_info_observation(Info12State.PRESENT))
    for index in range(100, 104):
        _process(controller, _returned_info_boss_frame(index, returned=True))
    assert controller.session is not None
    assert controller.session.boss_id == "boss.0"
    assert controller.session.enemy_type_ids is None

    _process(controller, _recovery_page_frame(104, phase=True))
    reminder = _process(controller, _recovery_page_frame(105, phase=True))
    assert reminder.recovery_reminder_visible is True
    assert reminder.missing_recoverable_items == ("enemy_types",)


def test_new_encounter_resets_pending_returned_info_boss_recovery() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(),
        catalog=_returned_info_catalog(),
        info_1_2_references=_returned_info_recovery_references(),
        info_recovery_page_references=_recovery_page_references(),
    )
    controller.apply_info_1_2_observation(_info_observation(Info12State.PRESENT))
    for index in range(105, 108):
        _process(controller, _returned_info_boss_frame(index, returned=True))
    assert controller._returned_info_boss_pending_count == 1  # noqa: SLF001

    for _ in range(3):
        controller.apply_info_1_2_observation(_info_observation(Info12State.ABSENT))
    for index in range(4):
        controller.apply_info_1_2_observation(_strict_next_info_observation(index))

    assert controller.session is not None
    assert controller.session.encounter_id == "live-encounter:2"
    assert controller._returned_info_boss_pending_count == 0  # noqa: SLF001


def test_returned_info_miss_never_erases_a_captured_boss() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(),
        catalog=_returned_info_catalog(),
        info_1_2_references=_returned_info_recovery_references(),
        info_recovery_page_references=_recovery_page_references(),
    )
    controller.apply_info_1_2_observation(_info_observation(Info12State.PRESENT))
    for index in range(110, 114):
        _process(controller, _returned_info_boss_frame(index, returned=True))
    after_miss = _process(controller, _recovery_page_frame(114))

    assert after_miss.session is not None
    assert after_miss.session.boss_id == "boss.0"


def test_new_info_candidate_does_not_contaminate_old_encounter_before_reentry_debounce() -> None:
    catalog = EncounterMapCatalog(
        definitions=(),
        difficulties=(
            DifficultyDefinition(
                difficulty_id="difficulty.synthetic.a",
                simulation_codes=("AC-1",),
                names=(LocalizedText(locale_id="zh_CN", text="A"),),
            ),
            DifficultyDefinition(
                difficulty_id="difficulty.synthetic.b",
                simulation_codes=("AC-2",),
                names=(LocalizedText(locale_id="zh_CN", text="B"),),
            ),
        ),
    )
    controller = LiveEncounterPreviewController(
        _FailingOcr(), catalog=catalog, info_1_2_references=_info_references()
    )
    for _ in range(2):
        controller.apply_info_1_2_observation(
            _info_observation(Info12State.PRESENT, difficulty_id="difficulty.synthetic.a")
        )
    old = controller.session
    assert old is not None and old.captured_difficulty is not None

    for _ in range(3):
        controller.apply_info_1_2_observation(_info_observation(Info12State.ABSENT))
    controller.apply_info_1_2_observation(
        _strict_next_info_observation(1, difficulty_id="difficulty.synthetic.b")
    )

    assert controller.session == old
    assert controller.session.captured_difficulty == old.captured_difficulty
    assert controller.session.difficulty_conflict is None
    candidate_diagnostic = json.loads(controller.diagnostic_json())
    assert candidate_diagnostic["encounter_id"] == "live-encounter:1"
    assert candidate_diagnostic["info_lifecycle_state"] == "armed_for_next_info"
    assert candidate_diagnostic["info_reentry_count"] == 1

    for _ in range(1):
        controller.apply_info_1_2_observation(
            _strict_next_info_observation(2, difficulty_id="difficulty.synthetic.b")
        )

    assert controller.session == old
    assert controller._info_reentry_count == 2  # noqa: SLF001

    controller.apply_info_1_2_observation(
        _strict_next_info_observation(3, difficulty_id="difficulty.synthetic.b")
    )

    assert controller.session is not None
    assert controller.session.encounter_id == "live-encounter:2"
    assert controller.session.captured_difficulty is None
    assert old.captured_difficulty.difficulty_id == "difficulty.synthetic.a"
    replacement_diagnostic = json.loads(controller.diagnostic_json())
    assert replacement_diagnostic["encounter_id"] == "live-encounter:2"
    assert replacement_diagnostic["info_lifecycle_state"] == "initial_info"
    assert replacement_diagnostic["info_departure_count"] == 0
    assert replacement_diagnostic["info_reentry_count"] == 0
    assert replacement_diagnostic["recovery_state"] == "inactive"


def test_historical_generic_info_transition_fixture_is_rejected_by_strict_classifier() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(), info_1_2_references=_info_references()
    )
    controller.apply_info_1_2_observation(_info_observation(Info12State.PRESENT))
    assert controller.session is not None
    controller._session = controller.session.model_copy(  # noqa: SLF001
        update={
            "captured_difficulty": CapturedDifficulty(
                difficulty_id="difficulty.covenant_latter.adversity",
                simulation_code="AC-2",
                capture_source=DifficultyCaptureSource.INITIAL_INFO_VISUAL,
            ),
            "boss_id": "boss.durable",
            "enemy_type_ids": ("enemy.durable.1", "enemy.durable.2"),
            "major_covenant_ban": _complete_major_ban_snapshot(),
        }
    )
    old = controller.session
    assert old.ordinary_progress_count == 3

    for _ in range(3):
        controller.apply_info_1_2_observation(_info_observation(Info12State.ABSENT))
    for _ in range(3):
        controller.apply_info_1_2_observation(
            _info_observation(
                Info12State.PRESENT,
                difficulty_id="difficulty.covenant_latter.deadland",
                reliable_enemy=False,
            )
        )
    controller.apply_info_1_2_observation(_info_observation(Info12State.ABSENT))

    assert controller.session == old
    assert controller.session.captured_difficulty == old.captured_difficulty
    assert controller.session.boss_id == old.boss_id
    assert controller.session.enemy_type_ids == old.enemy_type_ids
    assert controller.session.major_covenant_ban == old.major_covenant_ban
    assert controller.session.difficulty_conflict is None
    assert controller.session.ordinary_progress_count == old.ordinary_progress_count
    assert controller._info_reentry_count == 0  # noqa: SLF001
    diagnostic = json.loads(controller.diagnostic_json())
    assert diagnostic["next_initial_info_trace_rejection_counts"]["insufficient_structure"] == 3


@pytest.mark.parametrize("frame_count", (4, 20))
def test_generic_info_anchor_hits_never_replace_an_armed_encounter(frame_count: int) -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(), info_1_2_references=_info_references()
    )
    controller.apply_info_1_2_observation(_info_observation(Info12State.PRESENT))
    old = controller.session
    assert old is not None
    for _ in range(3):
        controller.apply_info_1_2_observation(_info_observation(Info12State.ABSENT))

    for index in range(frame_count):
        controller.apply_info_1_2_observation(_generic_present_observation(index))

    assert controller.session == old
    assert controller._info_reentry_count == 0  # noqa: SLF001
    diagnostic = json.loads(controller.diagnostic_json())
    assert diagnostic["next_initial_info_candidate"] is False
    assert diagnostic["next_initial_info_candidate_reason"] == "no_reliable_enemy"
    trace_rejections = diagnostic["next_initial_info_trace_rejection_counts"]
    assert trace_rejections["no_reliable_enemy"] == frame_count


@pytest.mark.parametrize(
    ("difficulty_id", "boss_id"),
    (
        ("difficulty.covenant_latter.deadland", None),
        (None, "boss.0"),
    ),
)
def test_armed_reentry_requires_a_reliable_enemy_not_only_difficulty_or_boss(
    difficulty_id: str | None,
    boss_id: str | None,
) -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(), info_1_2_references=_info_references()
    )
    controller.apply_info_1_2_observation(_info_observation(Info12State.PRESENT))
    old = controller.session
    assert old is not None
    for _ in range(3):
        controller.apply_info_1_2_observation(_info_observation(Info12State.ABSENT))

    for index in range(INFO_REENTRY_CONFIRMATION_COUNT + 1):
        controller.apply_info_1_2_observation(
            _structured_present_without_enemy(
                index,
                difficulty_id=difficulty_id,
                boss_id=boss_id,
            )
        )

    assert controller.session == old
    assert controller._info_reentry_count == 0  # noqa: SLF001
    diagnostic = json.loads(controller.diagnostic_json())
    assert diagnostic["next_initial_info_candidate_reason"] == "no_reliable_enemy"


def test_next_initial_info_trace_preserves_insufficient_structure_after_absence() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(), info_1_2_references=_info_references()
    )
    controller.apply_info_1_2_observation(_info_observation(Info12State.PRESENT))
    for _ in range(3):
        controller.apply_info_1_2_observation(_info_observation(Info12State.ABSENT))

    controller.apply_info_1_2_observation(
        _info_observation(Info12State.PRESENT, reliable_enemy=False)
    )
    controller.apply_info_1_2_observation(_info_observation(Info12State.ABSENT))

    diagnostic = json.loads(controller.diagnostic_json())
    assert diagnostic["info_reentry_count"] == 0
    assert diagnostic["next_initial_info_trace_present_frames"] == 1
    assert diagnostic["next_initial_info_trace_rejection_counts"]["insufficient_structure"] == 1
    assert diagnostic["next_initial_info_trace_last_rejection_reason"] == (
        "insufficient_structure"
    )
    assert diagnostic["next_initial_info_trace_last_present"]["classified_candidate"] is False
    assert diagnostic["next_initial_info_trace_last_present"]["classification_reason"] == (
        "insufficient_structure"
    )


def test_next_initial_info_trace_keeps_maximum_candidate_streak_after_absence() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(), info_1_2_references=_info_references()
    )
    controller.apply_info_1_2_observation(_info_observation(Info12State.PRESENT))
    old = controller.session
    for _ in range(3):
        controller.apply_info_1_2_observation(_info_observation(Info12State.ABSENT))
    for index in range(1, 3):
        controller.apply_info_1_2_observation(_strict_next_info_observation(index))
    controller.apply_info_1_2_observation(_info_observation(Info12State.ABSENT))

    diagnostic = json.loads(controller.diagnostic_json())
    assert controller.session == old
    assert diagnostic["info_reentry_count"] == 0
    assert diagnostic["next_initial_info_trace_candidate_frames"] == 2
    assert diagnostic["next_initial_info_trace_max_candidate_streak"] == 2
    assert diagnostic["next_initial_info_trace_last_candidate_frame_id"] == (
        "synthetic-strict-next:2"
    )


def test_three_consecutive_canonical_reentry_frames_start_exactly_one_fresh_encounter() -> None:
    assert INFO_REENTRY_CONFIRMATION_COUNT == 3

    controller = LiveEncounterPreviewController(
        _FailingOcr(), info_1_2_references=_info_references()
    )
    controller.apply_info_1_2_observation(_info_observation(Info12State.PRESENT))
    old = controller.session
    assert old is not None
    for _ in range(3):
        controller.apply_info_1_2_observation(_info_observation(Info12State.ABSENT))

    for expected_pending in range(1, 3):
        controller.apply_info_1_2_observation(_strict_next_info_observation(expected_pending))
        assert controller.session == old
        assert controller._info_reentry_count == expected_pending  # noqa: SLF001

    controller.apply_info_1_2_observation(_strict_next_info_observation(3))
    assert controller.session is not None
    assert controller.session.encounter_id == "live-encounter:2"
    assert controller.session.captured_difficulty is None
    diagnostic = json.loads(controller.diagnostic_json())
    assert diagnostic["next_initial_info_trace_present_frames"] == 0
    assert diagnostic["last_next_encounter_promotion_trace"] == {
        "max_candidate_streak": 3,
        "frame_id": "synthetic-strict-next:3",
        "promotion_reason": "confirmed_next_initial_info",
    }

    controller.apply_info_1_2_observation(_strict_next_info_observation(4))
    assert controller.session.captured_difficulty is not None
    assert (
        controller.session.captured_difficulty.difficulty_id
        == "difficulty.covenant_latter.deadland"
    )


@pytest.mark.parametrize("break_state", (Info12State.ABSENT, Info12State.UNRESOLVED))
def test_reentry_streak_resets_on_absent_or_unresolved_info(break_state: Info12State) -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(), info_1_2_references=_info_references()
    )
    controller.apply_info_1_2_observation(_info_observation(Info12State.PRESENT))
    old = controller.session
    assert old is not None
    for _ in range(3):
        controller.apply_info_1_2_observation(_info_observation(Info12State.ABSENT))

    controller.apply_info_1_2_observation(_strict_next_info_observation(1))
    controller.apply_info_1_2_observation(_strict_next_info_observation(2))
    controller.apply_info_1_2_observation(_info_observation(break_state))
    controller.apply_info_1_2_observation(_strict_next_info_observation(3))
    controller.apply_info_1_2_observation(_strict_next_info_observation(4))

    assert controller.session == old
    assert controller._info_reentry_count == 2  # noqa: SLF001


def test_returned_info_and_info_2_2_reset_the_strict_reentry_streak() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(), info_1_2_references=_info_references()
    )
    controller.apply_info_1_2_observation(_info_observation(Info12State.PRESENT))
    old = controller.session
    assert old is not None
    for _ in range(3):
        controller.apply_info_1_2_observation(_info_observation(Info12State.ABSENT))

    for index in range(1, 4):
        controller._latest_returned_info = InfoRecoveryPageObservation(  # noqa: SLF001
            InfoRecoveryPageState.PRESENT,
            f"synthetic-strict-next:{index}",
            0.99,
        )
        controller.apply_info_1_2_observation(_strict_next_info_observation(index))
        assert controller._info_reentry_count == 0  # noqa: SLF001
        assert controller._latest_next_initial_info_candidate is not None  # noqa: SLF001
        assert controller._latest_next_initial_info_candidate.reason == "returned_info"  # noqa: SLF001

    for index in range(4, 7):
        controller._latest_info_2_2_phase = InfoRecoveryPageObservation(  # noqa: SLF001
            InfoRecoveryPageState.PRESENT,
            f"synthetic-strict-next:{index}",
            0.99,
        )
        controller.apply_info_1_2_observation(_strict_next_info_observation(index))
        assert controller._info_reentry_count == 0  # noqa: SLF001
        assert controller._latest_next_initial_info_candidate is not None  # noqa: SLF001
        assert controller._latest_next_initial_info_candidate.reason == "info_2_2"  # noqa: SLF001

    for index in range(7, 9):
        controller.apply_info_1_2_observation(_strict_next_info_observation(index))
    assert controller.session == old
    assert controller._info_reentry_count == 2  # noqa: SLF001
    diagnostic = json.loads(controller.diagnostic_json())
    assert diagnostic["next_initial_info_trace_rejection_counts"]["returned_info"] == 3
    assert diagnostic["next_initial_info_trace_rejection_counts"]["info_2_2"] == 3


def test_new_encounter_clears_stale_controller_update_and_operation_metadata() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(), info_1_2_references=_info_references()
    )
    controller.apply_info_1_2_observation(_info_observation(Info12State.PRESENT))
    controller._update_status = EncounterUpdateStatus.CONFLICT  # noqa: SLF001
    controller._operation_state = OperationDifficultyState.OBSERVED  # noqa: SLF001
    for _ in range(3):
        controller.apply_info_1_2_observation(_info_observation(Info12State.ABSENT))
    for index in range(3):
        controller.apply_info_1_2_observation(_strict_next_info_observation(index))

    snapshot = controller.snapshot()
    diagnostic = json.loads(controller.diagnostic_json())

    assert snapshot.session is not None
    assert snapshot.session.encounter_id == "live-encounter:2"
    assert snapshot.update_status is None
    assert snapshot.operation_state is None
    assert diagnostic["encounter_update_status"] is None
    assert diagnostic["operation_state"] is None


def test_identical_consecutive_info_encounters_still_replace_the_session() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(), info_1_2_references=_info_references()
    )
    first = _info_observation(
        Info12State.PRESENT,
        difficulty_id="difficulty.covenant_latter.deadland",
    )
    controller.apply_info_1_2_observation(first)
    for _ in range(3):
        controller.apply_info_1_2_observation(_info_observation(Info12State.ABSENT))
    for index in range(3):
        controller.apply_info_1_2_observation(_strict_next_info_observation(index))

    assert controller.session is not None
    assert controller.session.encounter_id == "live-encounter:2"


def test_unresolved_info_does_not_arm_replacement() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(), info_1_2_references=_info_references()
    )
    controller.apply_info_1_2_observation(_info_observation(Info12State.PRESENT))
    for state in (
        Info12State.ABSENT,
        Info12State.ABSENT,
        Info12State.UNRESOLVED,
        Info12State.ABSENT,
        Info12State.ABSENT,
    ):
        controller.apply_info_1_2_observation(_info_observation(state))

    assert controller._info_lifecycle_state.value == "initial_info"  # noqa: SLF001


def test_capture_loss_preserves_armed_info_lifecycle_and_ordinary_recovery() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(), info_1_2_references=_info_references()
    )
    controller.apply_info_1_2_observation(_info_observation(Info12State.PRESENT))
    first = controller.session
    for _ in range(3):
        controller.apply_info_1_2_observation(_info_observation(Info12State.ABSENT))

    controller.capture_failed("MuMu renderer IPC connection was unavailable")
    _process(controller, _frame())

    assert controller.session == first
    assert controller._info_lifecycle_state.value == "armed_for_next_info"  # noqa: SLF001


def test_live_controller_presentation_locale_only_changes_the_view_and_diagnostics_are_local() -> (
    None
):
    controller = LiveEncounterPreviewController(
        _FailingOcr(), info_1_2_references=_info_references()
    )
    chinese = _process(controller, _info_frame())
    english = controller.set_locale("en")

    assert chinese.session == english.session
    assert chinese.presentation.title == "本局情报"
    assert english.presentation.title == "Encounter Intel"
    payload = json.loads(controller.diagnostic_json())
    assert payload["build"] == LIVE_ENCOUNTER_PREVIEW_BUILD
    assert payload["capture_dimensions"] == [1920, 1080]
    assert payload["profile"] == "jp_mumu_fullscreen_1920x1080.info_1_2.v1"
    assert payload["operation_ocr_enabled"] is False
    assert payload["info_reference_status"] == "available"
    assert payload["info_state"] == "present"
    assert payload["pending_difficulty_count"] == 1
    assert payload["pending_boss_count"] == 0
    assert payload["map_id"] is None
    assert payload["simulation_code"] is None
    assert payload["observed_difficulty"] is None
    assert "player" not in payload


def test_mumu_ipc_source_provenance_is_truthful_and_info_lifecycle_stays_source_neutral() -> None:
    metadata = FrameSourceMetadata(
        source_id="mumu-ipc:instance-0:display-0",
        source_type=FrameSourceType.MUMU_IPC,
        source_reference="mumu-renderer-ipc:instance=0,display=0",
        frame_rate=5.0,
    )
    controller = LiveEncounterPreviewController(
        _FailingOcr(),
        monitor_index=None,
        capture_source_metadata=metadata,
        info_1_2_references=_info_references(),
    )

    started = _process(controller, _mumu_info_frame())
    diagnostic = json.loads(controller.diagnostic_json())

    assert started.status is LiveEncounterPreviewStatus.RUNNING
    assert started.session is not None
    assert started.monitor_index is None
    assert started.capture_source_type is FrameSourceType.MUMU_IPC
    assert diagnostic["monitor_index"] is None
    assert diagnostic["capture_source_type"] == "mumu_ipc"
    assert diagnostic["capture_source_id"] == "mumu-ipc:instance-0:display-0"
    assert diagnostic["capture_source_reference"] == "mumu-renderer-ipc:instance=0,display=0"


def test_mumu_ipc_wrong_size_uses_existing_waiting_for_supported_frame_behavior() -> None:
    metadata = FrameSourceMetadata(
        source_id="mumu-ipc:instance-0:display-0",
        source_type=FrameSourceType.MUMU_IPC,
        source_reference="mumu-renderer-ipc:instance=0,display=0",
        frame_rate=5.0,
    )
    controller = LiveEncounterPreviewController(
        _FailingOcr(),
        monitor_index=None,
        capture_source_metadata=metadata,
        info_1_2_references=_info_references(),
    )

    snapshot = _process(controller, _mumu_frame(size=(1280, 720)))

    assert snapshot.status is LiveEncounterPreviewStatus.WAITING_FOR_SUPPORTED_FRAME


def test_mumu_ipc_startup_failure_retries_then_processes_a_frame() -> None:
    class _RecoveringMuMuSource(FrameSource):
        def __init__(self) -> None:
            self.attempts = 0

        @property
        def metadata(self) -> FrameSourceMetadata:
            return FrameSourceMetadata(
                source_id="mumu-ipc:instance-0:display-0",
                source_type=FrameSourceType.MUMU_IPC,
                source_reference="mumu-renderer-ipc:instance=0,display=0",
                frame_rate=5.0,
            )

        def frames(self) -> Iterator[Frame]:
            self.attempts += 1
            if self.attempts == 1:
                raise MuMuIpcCaptureError("MuMu renderer IPC connection was unavailable")
            yield _mumu_info_frame()

    controller = LiveEncounterPreviewController(
        _FailingOcr(), info_1_2_references=_info_references()
    )
    source = _RecoveringMuMuSource()
    snapshots: list[LiveEncounterPreviewSnapshot] = []
    waits: list[float] = []

    run_live_encounter_loop(
        source,
        controller,
        snapshots.append,
        reconnect_interval_seconds=1.0,
        retry_sleep=waits.append,
    )

    assert source.attempts == 2
    assert sum(waits) == pytest.approx(1.0)
    assert any(
        snapshot.status is LiveEncounterPreviewStatus.CAPTURE_UNAVAILABLE
        for snapshot in snapshots
    )
    assert any(snapshot.session is not None for snapshot in snapshots)
    assert snapshots[-1].status is LiveEncounterPreviewStatus.STOPPED


def test_mumu_ipc_disconnect_preserves_current_encounter_through_recovery() -> None:
    class _DisconnectingMuMuSource(FrameSource):
        def __init__(self) -> None:
            self.attempts = 0

        @property
        def metadata(self) -> FrameSourceMetadata:
            return FrameSourceMetadata(
                source_id="mumu-ipc:instance-0:display-0",
                source_type=FrameSourceType.MUMU_IPC,
                source_reference="mumu-renderer-ipc:instance=0,display=0",
                frame_rate=5.0,
            )

        def frames(self) -> Iterator[Frame]:
            self.attempts += 1
            if self.attempts == 1:
                yield _mumu_info_frame()
                raise MuMuIpcCaptureError("MuMu renderer IPC display capture failed")
            yield _mumu_frame(1)

    catalog = EncounterMapCatalog(
        definitions=(),
        difficulties=(
            DifficultyDefinition(
                difficulty_id="difficulty.synthetic.a",
                simulation_codes=("AC-3",),
                names=(LocalizedText(locale_id="zh_CN", text="A"),),
            ),
        ),
    )
    controller = LiveEncounterPreviewController(
        _FailingOcr(), catalog=catalog, info_1_2_references=_info_references()
    )
    source = _DisconnectingMuMuSource()
    snapshots: list[LiveEncounterPreviewSnapshot] = []

    def _capture_after_initial_info(snapshot: LiveEncounterPreviewSnapshot) -> None:
        snapshots.append(snapshot)
        if snapshot.session is not None and snapshot.latest_difficulty_id is None:
            controller.apply_operation_observation(
                _operation_observation("difficulty.synthetic.a", "A")
            )

    run_live_encounter_loop(
        source,
        controller,
        _capture_after_initial_info,
        retry_sleep=lambda _seconds: None,
    )

    assert source.attempts == 2
    assert controller.session is not None
    assert controller.session.encounter_id == "live-encounter:1"
    assert controller.session.captured_difficulty is not None
    assert controller.session.captured_difficulty.difficulty_id == "difficulty.synthetic.a"
    assert controller.snapshot().encounter_ended is False
    assert any(
        snapshot.status is LiveEncounterPreviewStatus.CAPTURE_UNAVAILABLE
        for snapshot in snapshots
    )


def test_mumu_ipc_retry_wait_stops_without_another_connection_attempt() -> None:
    class _UnavailableMuMuSource(FrameSource):
        def __init__(self) -> None:
            self.attempts = 0

        @property
        def metadata(self) -> FrameSourceMetadata:
            return FrameSourceMetadata(
                source_id="mumu-ipc:instance-0:display-0",
                source_type=FrameSourceType.MUMU_IPC,
                source_reference="mumu-renderer-ipc:instance=0,display=0",
                frame_rate=5.0,
            )

        def frames(self) -> Iterator[Frame]:
            self.attempts += 1
            raise MuMuIpcCaptureError("MuMu renderer IPC connection was unavailable")
            yield _mumu_frame()

    controller = LiveEncounterPreviewController(
        _FailingOcr(), info_1_2_references=_info_references()
    )
    source = _UnavailableMuMuSource()
    waits: list[float] = []

    def _stop_during_wait(seconds: float) -> None:
        waits.append(seconds)
        controller.stop()

    run_live_encounter_loop(
        source,
        controller,
        lambda _snapshot: None,
        retry_sleep=_stop_during_wait,
    )

    assert source.attempts == 1
    assert waits == [0.1]
    assert controller.snapshot().status is LiveEncounterPreviewStatus.STOPPED


def test_live_loop_stops_cleanly_after_one_frame() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(), info_1_2_references=_info_references()
    )
    snapshots: list[LiveEncounterPreviewSnapshot] = []
    run_live_encounter_loop(_Frames((_info_frame(),)), controller, snapshots.append)

    assert snapshots[-1].status is LiveEncounterPreviewStatus.STOPPED
    assert snapshots[0].presentation.progress_label == "0 / 5"


def test_supported_frame_waits_for_initial_info_with_a_distinct_status() -> None:
    controller = LiveEncounterPreviewController(
        _FailingOcr(), info_1_2_references=_info_references()
    )

    snapshot = _process(controller, _frame())

    assert snapshot.status is LiveEncounterPreviewStatus.WAITING_FOR_INITIAL_INFO
    assert snapshot.status_message != "等待受支持的 1920×1080 游戏画面"


@pytest.mark.parametrize(
    ("locale_id", "status", "expected"),
    (
        (
            "zh_CN",
            LiveEncounterPreviewStatus.WAITING_FOR_INITIAL_INFO,
            "已连接游戏画面，等待本局初始情報確認 1/2",
        ),
        ("zh_CN", LiveEncounterPreviewStatus.RUNNING, "正在监测本局游戏画面"),
        ("zh_CN", LiveEncounterPreviewStatus.CAPTURE_UNAVAILABLE, "无法获取游戏画面"),
        (
            "en",
            LiveEncounterPreviewStatus.WAITING_FOR_INITIAL_INFO,
            "Game capture connected. Waiting for the initial INFO 1/2.",
        ),
        ("en", LiveEncounterPreviewStatus.RUNNING, "Monitoring the current encounter"),
        ("en", LiveEncounterPreviewStatus.CAPTURE_UNAVAILABLE, "Game capture is unavailable"),
        (
            "en",
            LiveEncounterPreviewStatus.ENDED_WAITING_NEXT,
            "Previous encounter ended. Waiting for the next encounter.",
        ),
    ),
)
def test_status_messages_are_source_neutral(
    locale_id: str,
    status: LiveEncounterPreviewStatus,
    expected: str,
) -> None:
    assert _status_message(status, locale_id) == expected


def test_missing_info_references_remain_diagnosable_without_absolute_paths() -> None:
    failure = _sanitize_reference_load_failure(
        FileNotFoundError(2, "not found", r"C:\Users\gu\private\anchor.png")
    )
    controller = LiveEncounterPreviewController(
        _FailingOcr(),
        info_reference_failure=failure,
    )

    snapshot = _process(controller, _frame())
    payload = json.loads(controller.diagnostic_json())

    assert snapshot.status is LiveEncounterPreviewStatus.INFO_REFERENCES_UNAVAILABLE
    assert payload["info_reference_status"] == "unavailable"
    assert payload["info_reference_error_category"] == "missing_file"
    assert (
        payload["info_reference_error_reason"] == "required reference asset unavailable: anchor.png"
    )
    assert "C:\\Users" not in payload["info_reference_error_reason"]


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        (r"C:\Users\gu\private\anchor.png", "anchor.png"),
        ("/home/gu/private/anchor.png", "anchor.png"),
        (r"C:/Users\gu/private\anchor.png", "anchor.png"),
        (None, None),
    ),
)
def test_reference_asset_basename_is_cross_platform(
    source: str | None, expected: str | None
) -> None:
    assert _asset_basename(source) == expected


def test_existing_outside_run_debounce_ends_without_creating_or_resurrecting_an_encounter() -> None:
    controller = _active(LiveEncounterPreviewController(_QueueOcrBackend(["AC-3", "死地"])))
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


def test_live_preview_does_not_apply_outside_run_pages_to_end_watcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = _active(
        LiveEncounterPreviewController(
            _QueueOcrBackend(["AC-3", "死地"]), info_1_2_references=_info_references()
        )
    )
    called = False

    def _boom(observations: tuple[OutsideRunPageObservation, ...]) -> None:
        nonlocal called
        called = True
        raise AssertionError("live preview must not consult outside-run pages")

    monkeypatch.setattr(controller, "apply_outside_run_observations", _boom)

    snapshot = _process(controller, _info_frame())

    assert snapshot.status is LiveEncounterPreviewStatus.RUNNING
    assert snapshot.encounter_ended is False
    assert called is False


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
    controller = _active(LiveEncounterPreviewController(_QueueOcrBackend([]), catalog=catalog))
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
    assert controller.session is not None
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
