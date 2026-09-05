from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime

import numpy as np
import pytest

import sentry_copilot.services.live_encounter_preview as live_encounter_preview
from sentry_copilot.capture.frame_source import Frame, FrameSourceType
from sentry_copilot.encounter.catalog import EncounterMapCatalog
from sentry_copilot.encounter.lifecycle import begin_encounter
from sentry_copilot.encounter.major_covenant_ban_catalog import (
    MajorCovenantPresentationCatalog,
    MajorCovenantPresentationDefinition,
)
from sentry_copilot.encounter.models import (
    MAJOR_COVENANT_IDS,
    CapturedDifficulty,
    CovenantBanState,
    DifficultyCaptureSource,
    LocalizedText,
    MajorCovenantBanSnapshot,
    MajorCovenantBanStateEntry,
)
from sentry_copilot.encounter.presentation import present_encounter
from sentry_copilot.encounter.session import (
    EncounterUpdateStatus,
    apply_major_covenant_ban_capture,
)
from sentry_copilot.services.live_encounter_preview import (
    LiveEncounterPreviewController,
    _covenant_missing_label,
    _recovery_reminder_text,
)
from sentry_copilot.vision.info_1_2 import (
    EnemySlotLayout,
    Info12Observation,
    Info12State,
    RankedVisualCandidate,
)
from sentry_copilot.vision.info_recovery_pages import (
    InfoRecoveryPageObservation,
    InfoRecoveryPageState,
)
from sentry_copilot.vision.major_covenant_ban import (
    MAJOR_RECENTERED_CROP_SIZE,
    RETURNED_INFO_MAJOR_NOMINAL_CENTERS,
    MajorCovenantBanObservation,
    MajorCovenantBanObservationState,
    MajorCovenantBanObserver,
    MajorCovenantIdentityObservation,
    MajorCovenantReferencePack,
    MajorCovenantVisualReference,
    supports_initial_major_covenant_ban,
    supports_returned_major_covenant_ban,
)
from sentry_copilot.vision.viewport import ContentViewport

_IDS = tuple(sorted(MAJOR_COVENANT_IDS))
_DISABLED = _IDS[-3:]


def _snapshot(disabled: tuple[str, ...] = _DISABLED) -> MajorCovenantBanSnapshot:
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
            for covenant_id in _IDS
        )
    )


def _identity(
    index: int,
    covenant_id: str,
    state: CovenantBanState,
) -> MajorCovenantIdentityObservation:
    wrong = next(item for item in _IDS if item != covenant_id)
    return MajorCovenantIdentityObservation(
        candidate_index_for_extraction_only=index,
        refined_center=(0, 0),
        radius=50,
        state=state,
        state_saturation_median=230.0 if state is CovenantBanState.UNRESTRICTED else 50.0,
        ranking=(
            RankedVisualCandidate(covenant_id, 20.0),
            RankedVisualCandidate(wrong, 0.0),
        ),
    )


def _complete_observation(
    disabled: tuple[str, ...] = _DISABLED,
) -> MajorCovenantBanObservation:
    identities = tuple(
        _identity(
            index,
            covenant_id,
            CovenantBanState.DISABLED if covenant_id in disabled else CovenantBanState.UNRESTRICTED,
        )
        for index, covenant_id in enumerate(_IDS, start=1)
    )
    return MajorCovenantBanObservation(
        state=MajorCovenantBanObservationState.OBSERVED,
        frame_id="synthetic-major",
        supported=True,
        row_visible=True,
        candidate_count=8,
        identity_observations=identities,
        disabled_major_covenant_ids=disabled,
        structural_valid=True,
    )


def _presentation_catalog() -> MajorCovenantPresentationCatalog:
    return MajorCovenantPresentationCatalog(
        tuple(
            MajorCovenantPresentationDefinition(
                covenant_id=covenant_id,
                names=(LocalizedText(locale_id="zh_CN", text=f"名称{index}"),),
            )
            for index, covenant_id in enumerate(_IDS, start=1)
        )
    )


def _reference_pack() -> MajorCovenantReferencePack:
    references: list[MajorCovenantVisualReference] = []
    for index, covenant_id in enumerate(_IDS):
        image = np.random.default_rng(index).integers(
            0,
            256,
            size=(MAJOR_RECENTERED_CROP_SIZE, MAJOR_RECENTERED_CROP_SIZE, 3),
            dtype=np.uint8,
        )
        references.append(
            MajorCovenantVisualReference(
                covenant_id=covenant_id,
                state=CovenantBanState.UNRESTRICTED,
                image=image,
            )
        )
    return MajorCovenantReferencePack(tuple(references))


def _full_frame(frame_id: str = "synthetic-major") -> Frame:
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    return Frame(
        frame_id=frame_id,
        frame_index=0,
        processed_at=datetime(2026, 1, 1, tzinfo=UTC),
        source_timestamp=None,
        source_type=FrameSourceType.IMAGE_SEQUENCE,
        source_id="synthetic",
        source_reference="synthetic",
        width=1920,
        height=1080,
        image=image,
    )


def test_major_matcher_identity_comes_from_glyph_not_candidate_index() -> None:
    pack = _reference_pack()
    observer = MajorCovenantBanObserver(pack)
    expected = _IDS[4]
    query_image = next(item.image for item in pack.references if item.covenant_id == expected)

    observation = observer._observe_candidate((1, (265, 832), 50, query_image))  # noqa: SLF001

    assert observation.candidate_index_for_extraction_only == 1
    assert observation.covenant_id == expected
    assert observation.top_1_score is not None and observation.top_1_score >= 10
    assert observation.margin is not None and observation.margin >= 10


def test_major_identity_gate_rejects_low_score_or_low_margin() -> None:
    identity = _identity(1, _IDS[0], CovenantBanState.UNRESTRICTED)
    wrong = _IDS[1]
    low_score = replace(
        identity,
        ranking=(RankedVisualCandidate(_IDS[0], 9.0), RankedVisualCandidate(wrong, 0.0)),
    )
    low_margin = replace(
        identity,
        ranking=(RankedVisualCandidate(_IDS[0], 20.0), RankedVisualCandidate(wrong, 11.0)),
    )

    assert low_score.covenant_id is None
    assert low_margin.covenant_id is None


def test_major_state_classifier_keeps_unrestricted_and_disabled_independent_of_identity() -> None:
    observer = MajorCovenantBanObserver(_reference_pack())
    unrestricted = np.full(
        (MAJOR_RECENTERED_CROP_SIZE, MAJOR_RECENTERED_CROP_SIZE, 3),
        (0, 255, 0),
        dtype=np.uint8,
    )
    disabled = np.full_like(unrestricted, 64)

    unrestricted_observation = observer._observe_candidate(  # noqa: SLF001
        (1, (0, 0), 50, unrestricted)
    )
    disabled_observation = observer._observe_candidate((2, (0, 0), 50, disabled))  # noqa: SLF001

    assert unrestricted_observation.state is CovenantBanState.UNRESTRICTED
    assert disabled_observation.state is CovenantBanState.DISABLED


def test_major_complete_observation_rejects_duplicate_identity_and_wrong_state_count() -> None:
    complete = _complete_observation()
    duplicate = replace(
        complete,
        identity_observations=(
            replace(
                complete.identity_observations[0],
                ranking=complete.identity_observations[1].ranking,
            ),
            *complete.identity_observations[1:],
        ),
    )
    wrong_state_count = _complete_observation(_IDS[-2:])
    mismatched_disabled_ids = replace(complete, disabled_major_covenant_ids=_IDS[:3])

    assert complete.complete_reliable is True
    assert duplicate.complete_reliable is False
    assert wrong_state_count.complete_reliable is False
    assert mismatched_disabled_ids.complete_reliable is False
    assert (
        MajorCovenantBanObservation(
            MajorCovenantBanObservationState.ROW_ABSENT,
            "row-absent",
            True,
            False,
            0,
        ).complete_reliable
        is False
    )


def test_partial_identity_failure_never_pairs_states_with_wrong_ids_or_claims_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sentry_copilot.vision import major_covenant_ban

    observer = MajorCovenantBanObserver(_reference_pack())
    crop = np.zeros((MAJOR_RECENTERED_CROP_SIZE, MAJOR_RECENTERED_CROP_SIZE, 3), dtype=np.uint8)
    monkeypatch.setattr(
        major_covenant_ban,
        "_extract_candidate",
        lambda _image, index, _center: (index, (0, 0), 50, crop),
    )

    def partially_unreliable(
        candidate: tuple[int, tuple[int, int], int, np.ndarray],
        *,
        reference_cache: object | None = None,
    ) -> MajorCovenantIdentityObservation:
        del reference_cache
        result = _identity(candidate[0], _IDS[candidate[0] - 1], CovenantBanState.UNRESTRICTED)
        return (
            replace(
                result,
                ranking=(
                    RankedVisualCandidate(_IDS[0], 9.0),
                    RankedVisualCandidate(_IDS[1], 0.0),
                ),
            )
            if candidate[0] == 1
            else result
        )

    monkeypatch.setattr(observer, "_observe_candidate", partially_unreliable)
    frame = _full_frame()
    observation = observer.observe(
        frame,
        ContentViewport.full_frame(frame),
        info_state=Info12State.PRESENT,
        difficulty_id="difficulty.covenant_latter.adversity",
    )

    assert observation.state is MajorCovenantBanObservationState.UNRESOLVED
    assert observation.disabled_major_covenant_ids == ()
    assert observation.complete_reliable is False


def test_major_snapshot_requires_all_eight_unique_ids_and_five_three_state_structure() -> None:
    with pytest.raises(ValueError, match="every supported"):
        MajorCovenantBanSnapshot(covenant_states=_snapshot().covenant_states[:-1])
    with pytest.raises(ValueError, match="five unrestricted"):
        _snapshot(_IDS[-2:])


def test_major_capture_is_sticky_conflict_aware_and_never_completes_global_ban() -> None:
    initial = begin_encounter("major.capture")
    captured = apply_major_covenant_ban_capture(initial, _snapshot())
    repeated = apply_major_covenant_ban_capture(captured.session, _snapshot())
    conflict = apply_major_covenant_ban_capture(captured.session, _snapshot(_IDS[:3]))

    assert captured.status is EncounterUpdateStatus.CAPTURED
    assert captured.session.major_covenant_ban is not None
    assert captured.session.banned_covenant_ids is None
    assert captured.session.ordinary_progress_count == 0
    assert repeated.status is EncounterUpdateStatus.PRESERVED
    assert conflict.status is EncounterUpdateStatus.CONFLICT
    assert conflict.session.major_covenant_ban == captured.session.major_covenant_ban


def test_major_capture_requires_two_identical_observations_and_fresh_session_clears_it() -> None:
    controller = LiveEncounterPreviewController()
    controller._session = begin_encounter("major.controller")  # noqa: SLF001
    complete = _complete_observation()

    controller.apply_major_covenant_ban_observation(complete)
    assert controller.session is not None and controller.session.major_covenant_ban is None
    assert controller._major_ban_pending_count == 1  # noqa: SLF001

    controller.apply_major_covenant_ban_observation(complete)
    assert controller.session is not None and controller.session.major_covenant_ban is not None

    controller.apply_major_covenant_ban_observation(
        MajorCovenantBanObservation(
            MajorCovenantBanObservationState.ROW_ABSENT,
            "row-absent",
            True,
            False,
            0,
        )
    )
    assert controller.session is not None and controller.session.major_covenant_ban is not None

    controller._start_encounter()  # noqa: SLF001
    assert controller.session is not None
    assert controller.session.major_covenant_ban is None


def test_major_observer_skips_after_capture_and_reenables_for_a_fresh_encounter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SpyMajorObserver:
        calls = 0

        def observe(
            self,
            frame: Frame,
            viewport: ContentViewport,
            *,
            info_state: Info12State,
            difficulty_id: str | None,
        ) -> MajorCovenantBanObservation:
            del viewport, info_state, difficulty_id
            self.calls += 1
            return replace(_complete_observation(), frame_id=frame.frame_id)

    spy = _SpyMajorObserver()
    monkeypatch.setattr(
        live_encounter_preview,
        "MajorCovenantBanObserver",
        lambda _references: spy,
    )
    controller = LiveEncounterPreviewController(major_covenant_references=_reference_pack())
    frame = _full_frame("major-cached")
    viewport = ContentViewport.full_frame(frame)
    info = Info12Observation(
        Info12State.PRESENT,
        frame.frame_id,
        0.99,
        enemy_rankings=(
            (
                RankedVisualCandidate("enemy.synthetic", 0.99),
                RankedVisualCandidate("enemy.other", 0.01),
            ),
            (),
        ),
        enemy_slot_layout=EnemySlotLayout.TWO_SLOT,
    )
    controller.apply_info_1_2_observation(info)

    controller._observe_initial_info_major_ban(frame, viewport, info)  # noqa: SLF001
    assert spy.calls == 1
    latest_before_capture = controller._latest_major_covenant_ban  # noqa: SLF001

    assert controller.session is not None
    controller._session = controller.session.model_copy(  # noqa: SLF001
        update={"major_covenant_ban": _snapshot()}
    )
    controller._observe_initial_info_major_ban(frame, viewport, info)  # noqa: SLF001

    assert spy.calls == 1
    assert controller._latest_major_covenant_ban is latest_before_capture  # noqa: SLF001
    assert controller._major_ban_pending_count == 0  # noqa: SLF001

    for index in range(3):
        controller.apply_info_1_2_observation(
            Info12Observation(Info12State.ABSENT, f"major-departure:{index}", 0.01)
        )
    for index in range(4):
        controller.apply_info_1_2_observation(
            Info12Observation(
                Info12State.PRESENT,
                f"major-next-info:{index}",
                0.99,
                enemy_rankings=(
                    (
                        RankedVisualCandidate("enemy.synthetic", 0.99),
                        RankedVisualCandidate("enemy.other", 0.01),
                    ),
                    (),
                ),
                enemy_slot_layout=EnemySlotLayout.TWO_SLOT,
                difficulty_ranking=(
                    RankedVisualCandidate("difficulty.covenant_latter.deadland", 0.99),
                    RankedVisualCandidate("difficulty.other", 0.01),
                ),
            )
        )

    assert controller.session is not None
    assert controller.session.encounter_id == "live-encounter:2"
    controller._observe_initial_info_major_ban(frame, viewport, info)  # noqa: SLF001

    assert spy.calls == 2


def test_conflicting_or_unresolved_major_frames_reset_the_pending_set() -> None:
    controller = LiveEncounterPreviewController()
    controller._session = begin_encounter("major.pending")  # noqa: SLF001
    controller.apply_major_covenant_ban_observation(_complete_observation())
    controller.apply_major_covenant_ban_observation(
        MajorCovenantBanObservation(
            MajorCovenantBanObservationState.UNRESOLVED,
            "unresolved",
            True,
            True,
            8,
        )
    )
    controller.apply_major_covenant_ban_observation(_complete_observation(_IDS[:3]))

    assert controller.session is not None and controller.session.major_covenant_ban is None
    assert controller._major_ban_pending_count == 1  # noqa: SLF001


def test_standard_is_explicitly_unsupported_before_major_row_extraction() -> None:
    observer = MajorCovenantBanObserver(_reference_pack())
    frame = _full_frame("standard")
    observation = observer.observe(
        frame,
        ContentViewport.full_frame(frame),
        info_state=Info12State.PRESENT,
        difficulty_id="difficulty.covenant_latter.standard",
    )

    assert observation.state is MajorCovenantBanObservationState.UNSUPPORTED
    assert observation.candidate_count == 0


def test_returned_major_requires_returned_page_and_supported_difficulty() -> None:
    observer = MajorCovenantBanObserver(_reference_pack())
    frame = _full_frame("returned-major-gate")
    viewport = ContentViewport.full_frame(frame)

    absent = observer.observe_returned_info(
        frame,
        viewport,
        returned_info_state=InfoRecoveryPageState.ABSENT,
        difficulty_id="difficulty.covenant_latter.deadland",
    )
    standard = observer.observe_returned_info(
        frame,
        viewport,
        returned_info_state=InfoRecoveryPageState.PRESENT,
        difficulty_id="difficulty.covenant_latter.standard",
    )

    assert absent.state is MajorCovenantBanObservationState.UNRESOLVED
    assert absent.reason == "requires_returned_info_page"
    assert standard.state is MajorCovenantBanObservationState.UNSUPPORTED
    assert standard.reason == "difficulty_not_supported_for_major_ban"


def test_returned_major_windows_locate_candidates_but_glyphs_choose_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sentry_copilot.vision import major_covenant_ban

    pack = _reference_pack()
    observer = MajorCovenantBanObserver(pack)
    expected = _IDS[4]
    query_ids = (expected, *_IDS[:4], *_IDS[5:])
    images = {
        covenant_id: next(item.image for item in pack.references if item.covenant_id == covenant_id)
        for covenant_id in query_ids
    }
    centers: list[tuple[int, int]] = []

    def extract(
        _image: np.ndarray,
        index: int,
        center: tuple[int, int],
    ) -> tuple[int, tuple[int, int], int, np.ndarray]:
        centers.append(center)
        return index, center, 50, images[query_ids[index - 1]]

    monkeypatch.setattr(major_covenant_ban, "_extract_candidate", extract)
    frame = _full_frame("returned-major-identity")
    observation = observer.observe_returned_info(
        frame,
        ContentViewport.full_frame(frame),
        returned_info_state=InfoRecoveryPageState.PRESENT,
        difficulty_id="difficulty.covenant_latter.deadland",
    )

    assert centers == list(RETURNED_INFO_MAJOR_NOMINAL_CENTERS)
    assert observation.identity_observations[0].candidate_index_for_extraction_only == 1
    assert observation.identity_observations[0].covenant_id == expected


def test_returned_major_two_frame_fill_missing_recovery_is_gated_and_sticky(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SpyMajorObserver:
        calls = 0
        unresolved = False

        def observe(
            self,
            frame: Frame,
            viewport: ContentViewport,
            *,
            info_state: Info12State,
            difficulty_id: str | None,
        ) -> MajorCovenantBanObservation:
            del viewport, info_state, difficulty_id
            return replace(_complete_observation(), frame_id=frame.frame_id)

        def observe_returned_info(
            self,
            frame: Frame,
            viewport: ContentViewport,
            *,
            returned_info_state: InfoRecoveryPageState,
            difficulty_id: str | None,
        ) -> MajorCovenantBanObservation:
            del viewport, returned_info_state, difficulty_id
            self.calls += 1
            if self.unresolved:
                return MajorCovenantBanObservation(
                    MajorCovenantBanObservationState.UNRESOLVED,
                    frame.frame_id,
                    True,
                    True,
                    8,
                )
            return replace(_complete_observation(), frame_id=frame.frame_id)

    spy = _SpyMajorObserver()
    monkeypatch.setattr(
        live_encounter_preview,
        "MajorCovenantBanObserver",
        lambda _references: spy,
    )
    controller = LiveEncounterPreviewController(major_covenant_references=_reference_pack())
    frame = _full_frame("returned-major-controller")
    viewport = ContentViewport.full_frame(frame)

    controller._observe_returned_info_major_recovery(frame, viewport)  # noqa: SLF001
    assert spy.calls == 0

    controller._latest_returned_info = InfoRecoveryPageObservation(  # noqa: SLF001
        InfoRecoveryPageState.PRESENT,
        frame.frame_id,
        0.99,
    )
    controller._session = begin_encounter("returned-major").model_copy(  # noqa: SLF001
        update={
            "captured_difficulty": CapturedDifficulty(
                difficulty_id="difficulty.covenant_latter.deadland",
                simulation_code="AC-3",
                capture_source=DifficultyCaptureSource.INITIAL_INFO_VISUAL,
            ),
            "boss_id": "boss.captured",
            "enemy_type_ids": ("enemy.a", "enemy.b", "enemy.c"),
        }
    )

    controller._latest_returned_info = InfoRecoveryPageObservation(  # noqa: SLF001
        InfoRecoveryPageState.ABSENT,
        frame.frame_id,
        0.01,
    )
    controller._observe_returned_info_major_recovery(frame, viewport)  # noqa: SLF001
    assert spy.calls == 0

    controller._latest_returned_info = InfoRecoveryPageObservation(  # noqa: SLF001
        InfoRecoveryPageState.PRESENT,
        frame.frame_id,
        0.99,
    )
    controller._observe_returned_info_major_recovery(frame, viewport)  # noqa: SLF001
    assert spy.calls == 1
    assert controller.session is not None and controller.session.major_covenant_ban is None
    assert controller._returned_info_major_pending_count == 1  # noqa: SLF001
    diagnostics = json.loads(controller.diagnostic_json())
    assert diagnostics["returned_info_major_state"] == "observed"
    assert diagnostics["returned_info_major_candidate_count"] == 8
    assert diagnostics["returned_info_major_pending_count"] == 1
    assert diagnostics["returned_info_major_capture_attempted"] is True

    controller._latest_returned_info = InfoRecoveryPageObservation(  # noqa: SLF001
        InfoRecoveryPageState.ABSENT,
        frame.frame_id,
        0.01,
    )
    controller._observe_returned_info_major_recovery(frame, viewport)  # noqa: SLF001
    absent_diagnostics = json.loads(controller.diagnostic_json())
    assert spy.calls == 1
    assert absent_diagnostics["returned_info_major_state"] is None
    assert absent_diagnostics["returned_info_major_candidate_count"] == 0
    assert absent_diagnostics["returned_info_major_capture_attempted"] is False

    spy.unresolved = True
    controller._latest_returned_info = InfoRecoveryPageObservation(  # noqa: SLF001
        InfoRecoveryPageState.PRESENT,
        frame.frame_id,
        0.99,
    )
    controller._observe_returned_info_major_recovery(frame, viewport)  # noqa: SLF001
    assert spy.calls == 2
    assert controller._returned_info_major_pending_count == 0  # noqa: SLF001

    spy.unresolved = False
    controller._observe_returned_info_major_recovery(frame, viewport)  # noqa: SLF001
    controller._observe_returned_info_major_recovery(frame, viewport)  # noqa: SLF001
    assert spy.calls == 4
    assert controller.session is not None
    assert controller.session.major_covenant_ban == _snapshot()
    assert controller.session.ordinary_progress_count == 3

    controller._observe_returned_info_major_recovery(frame, viewport)  # noqa: SLF001
    assert spy.calls == 4
    assert controller._returned_info_major_capture_attempted is False  # noqa: SLF001
    after_capture_diagnostics = json.loads(controller.diagnostic_json())
    assert after_capture_diagnostics["returned_info_major_state"] is None
    assert controller.session is not None and controller.session.major_covenant_ban == _snapshot()

    controller._start_encounter()  # noqa: SLF001
    assert controller.session is not None and controller.session.major_covenant_ban is None
    controller._session = controller.session.model_copy(  # noqa: SLF001
        update={
            "captured_difficulty": CapturedDifficulty(
                difficulty_id="difficulty.covenant_latter.adversity",
                simulation_code="AC-2",
                capture_source=DifficultyCaptureSource.INITIAL_INFO_VISUAL,
            )
        }
    )
    controller._latest_returned_info = InfoRecoveryPageObservation(  # noqa: SLF001
        InfoRecoveryPageState.PRESENT,
        frame.frame_id,
        0.99,
    )
    controller._observe_returned_info_major_recovery(frame, viewport)  # noqa: SLF001
    assert spy.calls == 5


@pytest.mark.parametrize(
    ("difficulty_id", "simulation_code", "expected_major_missing"),
    (
        ("difficulty.covenant_latter.adversity", "AC-2", True),
        ("difficulty.covenant_latter.deadland", "AC-3", True),
        ("difficulty.covenant_latter.standard", "AC-1", False),
        ("difficulty.covenant_latter.ultimate", "AC-4", True),
        (None, None, False),
    ),
)
def test_missing_recoverable_major_is_limited_to_supported_difficulties(
    difficulty_id: str | None,
    simulation_code: str | None,
    expected_major_missing: bool,
) -> None:
    controller = LiveEncounterPreviewController(major_covenant_references=_reference_pack())
    session = begin_encounter("major-reminder")
    if difficulty_id is not None:
        session = session.model_copy(
            update={
                "captured_difficulty": CapturedDifficulty(
                    difficulty_id=difficulty_id,
                    simulation_code=simulation_code or "AC-1",
                    capture_source=DifficultyCaptureSource.INITIAL_INFO_VISUAL,
                )
            }
        )
    controller._session = session  # noqa: SLF001

    missing = controller._missing_recoverable_items()  # noqa: SLF001

    assert ("major_covenants" in missing) is expected_major_missing
    assert "additional_covenants" not in missing


def test_ultimate_major_support_is_returned_info_only_until_initial_glyph_validation_passes(
) -> None:
    ultimate_id = "difficulty.covenant_latter.ultimate"

    assert not supports_initial_major_covenant_ban(ultimate_id)
    assert supports_returned_major_covenant_ban(ultimate_id)


def test_missing_supported_major_is_not_recoverable_without_available_observer() -> None:
    controller = LiveEncounterPreviewController()
    controller._session = begin_encounter("major-reminder-unavailable").model_copy(  # noqa: SLF001
        update={
            "captured_difficulty": CapturedDifficulty(
                difficulty_id="difficulty.covenant_latter.deadland",
                simulation_code="AC-3",
                capture_source=DifficultyCaptureSource.INITIAL_INFO_VISUAL,
            )
        }
    )

    assert "major_covenants" not in controller._missing_recoverable_items()  # noqa: SLF001


def test_captured_major_is_not_recoverable_and_keeps_boss_enemy_composition() -> None:
    controller = LiveEncounterPreviewController()
    controller._session = begin_encounter("major-reminder-captured").model_copy(  # noqa: SLF001
        update={
            "captured_difficulty": CapturedDifficulty(
                difficulty_id="difficulty.covenant_latter.deadland",
                simulation_code="AC-3",
                capture_source=DifficultyCaptureSource.INITIAL_INFO_VISUAL,
            ),
            "major_covenant_ban": _snapshot(),
        }
    )

    assert controller._missing_recoverable_items() == ("boss", "enemy_types")  # noqa: SLF001
    assert controller.session is not None
    controller._session = controller.session.model_copy(update={"boss_id": "boss.known"})  # noqa: SLF001
    assert controller._missing_recoverable_items() == ("enemy_types",)  # noqa: SLF001


@pytest.mark.parametrize(
    ("major_missing", "additional_missing", "zh_label", "en_label"),
    (
        (True, True, "盟约未识别", "Covenants not captured"),
        (True, False, "主盟约未识别", "Major Covenants not captured"),
        (False, True, "追加盟约未识别", "Additional Covenants not captured"),
        (False, False, None, None),
    ),
)
def test_covenant_missing_label_matrix(
    major_missing: bool,
    additional_missing: bool,
    zh_label: str | None,
    en_label: str | None,
) -> None:
    assert _covenant_missing_label(major_missing, additional_missing, "zh_CN") == zh_label
    assert _covenant_missing_label(major_missing, additional_missing, "en") == en_label


def test_covenant_recovery_reminder_formats_major_and_additional_components() -> None:
    assert _recovery_reminder_text(
        "zh_CN", ("major_covenants", "additional_covenants")
    ).endswith("待补充：盟约未识别")
    assert _recovery_reminder_text("zh_CN", ("major_covenants",)).endswith(
        "待补充：主盟约未识别"
    )
    assert _recovery_reminder_text("zh_CN", ("additional_covenants",)).endswith(
        "待补充：追加盟约未识别"
    )
    assert _recovery_reminder_text("zh_CN", ("boss", "additional_covenants")).endswith(
        "待补充：Boss / 追加盟约未识别"
    )
    assert _recovery_reminder_text("zh_CN", ("boss", "major_covenants")).endswith(
        "待补充：Boss / 主盟约未识别"
    )
    assert _recovery_reminder_text("zh_CN", ("enemy_types", "major_covenants")).endswith(
        "待补充：敌人类型 / 主盟约未识别"
    )


def test_returned_major_skips_standard_before_constructing_expensive_observer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailIfCalled:
        def observe(self, *args: object, **kwargs: object) -> MajorCovenantBanObservation:
            raise AssertionError("initial observer must not run")

        def observe_returned_info(
            self, *args: object, **kwargs: object
        ) -> MajorCovenantBanObservation:
            raise AssertionError("returned observer must not run for Standard")

    monkeypatch.setattr(
        live_encounter_preview,
        "MajorCovenantBanObserver",
        lambda _references: _FailIfCalled(),
    )
    controller = LiveEncounterPreviewController(major_covenant_references=_reference_pack())
    frame = _full_frame("returned-major-standard")
    controller._session = begin_encounter("returned-standard").model_copy(  # noqa: SLF001
        update={
            "captured_difficulty": CapturedDifficulty(
                difficulty_id="difficulty.covenant_latter.standard",
                simulation_code="AC-1",
                capture_source=DifficultyCaptureSource.INITIAL_INFO_VISUAL,
            )
        }
    )
    controller._latest_returned_info = InfoRecoveryPageObservation(  # noqa: SLF001
        InfoRecoveryPageState.PRESENT,
        frame.frame_id,
        0.99,
    )

    controller._observe_returned_info_major_recovery(  # noqa: SLF001
        frame,
        ContentViewport.full_frame(frame),
    )

    assert controller.session is not None and controller.session.major_covenant_ban is None


@pytest.mark.parametrize(
    "difficulty_id",
    (
        "difficulty.covenant_latter.adversity",
        "difficulty.covenant_latter.deadland",
    ),
)
def test_supported_difficulties_attempt_major_row_extraction(difficulty_id: str) -> None:
    observer = MajorCovenantBanObserver(_reference_pack())
    frame = _full_frame(difficulty_id)

    observation = observer.observe(
        frame,
        ContentViewport.full_frame(frame),
        info_state=Info12State.PRESENT,
        difficulty_id=difficulty_id,
    )

    assert observation.state is MajorCovenantBanObservationState.ROW_ABSENT
    assert observation.supported is True


def test_major_presentation_is_partial_and_uses_catalog_names_without_progress_completion() -> None:
    session = begin_encounter("major.presentation").model_copy(
        update={"major_covenant_ban": _snapshot()}
    )
    view = present_encounter(
        session,
        EncounterMapCatalog(definitions=()),
        locale_id="zh_CN",
        major_covenant_catalog=_presentation_catalog(),
    )
    ban = view.items[3]

    assert ban.complete is False
    assert ban.implemented is True
    assert all(name in ban.value for name in ("名称6", "名称7", "名称8"))
    assert session.ordinary_progress_count == 0
