"""Focused contracts for the bounded Additional Covenant Ban prototype."""

from __future__ import annotations

import json

import numpy as np
import pytest

import sentry_copilot.vision.additional_covenant_ban as additional_ban
from sentry_copilot.encounter.additional_covenant_ban_catalog import (
    AdditionalCovenantPresentationCatalog,
    AdditionalCovenantPresentationDefinition,
)
from sentry_copilot.encounter.catalog import EncounterMapCatalog
from sentry_copilot.encounter.confirmed_banned_operators import (
    BannedOperatorDefinition,
    ConfirmedBannedOperatorCatalog,
    CovenantDefinition,
)
from sentry_copilot.encounter.lifecycle import begin_encounter
from sentry_copilot.encounter.major_covenant_ban_catalog import (
    MajorCovenantPresentationCatalog,
    MajorCovenantPresentationDefinition,
)
from sentry_copilot.encounter.models import (
    ADDITIONAL_COVENANT_IDS,
    MAJOR_COVENANT_IDS,
    AdditionalCovenantBanCaptureSource,
    AdditionalCovenantBanSnapshot,
    CapturedDifficulty,
    CovenantBanState,
    LocalizedText,
    MajorCovenantBanSnapshot,
    MajorCovenantBanStateEntry,
)
from sentry_copilot.encounter.presentation import present_encounter
from sentry_copilot.encounter.session import (
    EncounterUpdateStatus,
    apply_additional_covenant_ban_capture,
    apply_major_covenant_ban_capture,
)
from sentry_copilot.services.live_encounter_preview import LiveEncounterPreviewController
from sentry_copilot.vision.additional_covenant_ban import (
    AdditionalCovenantBanObservation,
    AdditionalCovenantBanObservationState,
    AdditionalCovenantBanObserver,
    AdditionalCovenantReferencePack,
    AdditionalCovenantVisualReference,
    _select_surface_layout,
    supports_additional_covenant_ban,
)

_ADDITIONAL_IDS = tuple(sorted(ADDITIONAL_COVENANT_IDS))
_MAJOR_IDS = tuple(sorted(MAJOR_COVENANT_IDS))


def _row(count: int, y: int) -> list[tuple[int, int, int]]:
    return [(250 + index * 150, y, 52) for index in range(count)]


def _five_of_six_second_row(missing_index: int, y: int = 780) -> list[tuple[int, int, int]]:
    return [
        (263 + index * 172, y, 52)
        for index in range(6)
        if index != missing_index
    ]


def _six_slot_row_with_trailing_residue(
    extra_count: int,
    y: int,
) -> list[tuple[int, int, int]]:
    return [
        *((263 + index * 172, y, 52) for index in range(6)),
        *((1295 + index * 172, y, 52) for index in range(extra_count)),
    ]


def _additional_snapshot(
    ids: tuple[str, ...] = _ADDITIONAL_IDS[:4],
) -> AdditionalCovenantBanSnapshot:
    return AdditionalCovenantBanSnapshot(
        disabled_covenant_ids=ids,
        capture_source=AdditionalCovenantBanCaptureSource.INITIAL_INFO_VISUAL,
        confirmed_frame_id="additional-frame",
    )


def _major_snapshot() -> MajorCovenantBanSnapshot:
    disabled = frozenset(_MAJOR_IDS[:3])
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
            for covenant_id in _MAJOR_IDS
        )
    )


def _presentation_catalogs() -> tuple[
    MajorCovenantPresentationCatalog, AdditionalCovenantPresentationCatalog
]:
    return (
        MajorCovenantPresentationCatalog(
            tuple(
                MajorCovenantPresentationDefinition(
                    covenant_id, (LocalizedText(locale_id="zh_CN", text=f"主{index}"),)
                )
                for index, covenant_id in enumerate(_MAJOR_IDS, start=1)
            )
        ),
        AdditionalCovenantPresentationCatalog(
            tuple(
                AdditionalCovenantPresentationDefinition(
                    covenant_id, (LocalizedText(locale_id="zh_CN", text=f"追{index}"),)
                )
                for index, covenant_id in enumerate(_ADDITIONAL_IDS, start=1)
            )
        ),
    )


def _ban_value(session: object) -> str:
    major, additional = _presentation_catalogs()
    view = present_encounter(
        session,  # type: ignore[arg-type]
        EncounterMapCatalog(definitions=()),
        locale_id="zh_CN",
        major_covenant_catalog=major,
        additional_covenant_catalog=additional,
    )
    return view.items[3].value


def test_additional_snapshot_requires_exactly_four_distinct_known_ids() -> None:
    with pytest.raises(ValueError, match="four distinct"):
        _additional_snapshot((_ADDITIONAL_IDS[0],) * 4)
    with pytest.raises(ValueError, match="four distinct"):
        _additional_snapshot(
            (_ADDITIONAL_IDS[0], _ADDITIONAL_IDS[1], "unknown", _ADDITIONAL_IDS[2])
        )


def test_major_and_additional_are_both_required_for_the_ordinary_ban_item() -> None:
    initial = begin_encounter("additional.complete")
    major_only = apply_major_covenant_ban_capture(initial, _major_snapshot())
    additional_only = apply_additional_covenant_ban_capture(initial, _additional_snapshot())
    full = apply_additional_covenant_ban_capture(major_only.session, _additional_snapshot())

    assert major_only.session.banned_covenant_ids is None
    assert additional_only.session.banned_covenant_ids is None
    assert full.status is EncounterUpdateStatus.CAPTURED
    assert full.session.banned_covenant_ids is not None
    assert len(full.session.banned_covenant_ids) == 7
    supported_capture = full.session.model_copy(
        update={
            "captured_difficulty": CapturedDifficulty(
                difficulty_id="difficulty.covenant_latter.adversity",
                simulation_code="AC-2",
            ),
            "boss_id": "boss.synthetic",
            "enemy_type_ids": ("enemy.one", "enemy.two"),
        }
    )
    assert supported_capture.ordinary_progress_count == 4
    view = present_encounter(supported_capture, EncounterMapCatalog(definitions=()), locale_id="en")
    assert view.progress_label == "4 / 4"
    assert len(view.items) == 4
    assert all(item.complete for item in view.items)
    assert len(full.session.complete_items) == 1  # Major + Additional is one Ban product item.
    reverse = apply_major_covenant_ban_capture(additional_only.session, _major_snapshot())
    assert reverse.session.banned_covenant_ids == full.session.banned_covenant_ids


def test_complete_supported_live_snapshot_and_diagnostics_reach_four_of_four() -> None:
    session = begin_encounter("encounter.complete").model_copy(
        update={
            "captured_difficulty": CapturedDifficulty(
                difficulty_id="difficulty.covenant_latter.adversity",
                simulation_code="AC-2",
            ),
            "boss_id": "boss.synthetic",
            "enemy_type_ids": ("enemy.one", "enemy.two"),
        }
    )
    session = apply_major_covenant_ban_capture(session, _major_snapshot()).session
    session = apply_additional_covenant_ban_capture(session, _additional_snapshot()).session
    controller = LiveEncounterPreviewController()
    controller._session = session  # noqa: SLF001

    snapshot = controller.snapshot()
    diagnostic = json.loads(controller.diagnostic_json())

    assert snapshot.presentation.progress_label == diagnostic["progress"] == "4 / 4"
    assert len(snapshot.presentation.items) == 4
    assert all(item.complete for item in snapshot.presentation.items)
    assert session.missing_items == ()
    assert "map_id" not in diagnostic
    assert "captured_map" not in session.model_dump()
    assert not hasattr(snapshot, "latest_map_id")


def test_ban_presentation_keeps_major_and_additional_snapshots_independent() -> None:
    initial = begin_encounter("additional.presentation")
    major_only = apply_major_covenant_ban_capture(initial, _major_snapshot()).session
    additional_only = apply_additional_covenant_ban_capture(initial, _additional_snapshot()).session
    both = apply_additional_covenant_ban_capture(major_only, _additional_snapshot()).session

    assert _ban_value(initial) == "主盟约：尚未识别\n追加盟约：尚未识别"
    assert _ban_value(major_only).startswith("主盟约：主")
    assert _ban_value(major_only).endswith("\n追加盟约：尚未识别")
    assert _ban_value(additional_only).startswith("主盟约：尚未识别\n追加盟约：追")
    assert _ban_value(both).count("\n") == 1
    assert both.banned_covenant_ids is not None


def test_confirmed_ban_detail_rows_are_major_then_additional_with_no_loss() -> None:
    major_ids = _MAJOR_IDS[:3]
    additional_ids = _ADDITIONAL_IDS[:4]
    covenant_ids = (*major_ids, *additional_ids)
    catalog = ConfirmedBannedOperatorCatalog(
        operators=tuple(
            BannedOperatorDefinition(f"operator.{index}", f"干员{index}", 5)
            for index in range(7)
        ),
        covenant_definitions=tuple(
            CovenantDefinition(covenant_id, covenant_id, True, True)
            for covenant_id in covenant_ids
        ),
        membership_ids_by_operator=tuple(
            (f"operator.{index}", (covenant_id,))
            for index, covenant_id in enumerate(covenant_ids)
        ),
    )
    session = begin_encounter("additional.grouping").model_copy(
        update={"banned_covenant_ids": frozenset(covenant_ids)}
    )

    view = present_encounter(
        session,
        EncounterMapCatalog(definitions=()),
        locale_id="zh_CN",
        confirmed_banned_operator_catalog=catalog,
    )

    assert len(view.confirmed_banned_operator_rows) == 7
    assert {row.covenant_id for row in view.confirmed_banned_operator_rows} == set(covenant_ids)
    assert all(
        row.covenant_id in MAJOR_COVENANT_IDS
        for row in view.confirmed_banned_operator_rows[:3]
    )
    assert all(
        row.covenant_id in ADDITIONAL_COVENANT_IDS
        for row in view.confirmed_banned_operator_rows[3:]
    )


def test_additional_only_confirmed_ban_evidence_projects_additional_detail_rows() -> None:
    additional_ids = _ADDITIONAL_IDS[:4]
    catalog = ConfirmedBannedOperatorCatalog(
        operators=tuple(
            BannedOperatorDefinition(f"operator.{index}", f"干员{index}", 5)
            for index in range(4)
        ),
        covenant_definitions=tuple(
            CovenantDefinition(covenant_id, covenant_id, True, True)
            for covenant_id in additional_ids
        ),
        membership_ids_by_operator=tuple(
            (f"operator.{index}", (covenant_id,))
            for index, covenant_id in enumerate(additional_ids)
        ),
    )
    session = apply_additional_covenant_ban_capture(
        begin_encounter("additional.only.detail"), _additional_snapshot(additional_ids)
    ).session

    view = present_encounter(
        session,
        EncounterMapCatalog(definitions=()),
        locale_id="zh_CN",
        confirmed_banned_operator_catalog=catalog,
    )

    assert [row.covenant_id for row in view.confirmed_banned_operator_rows] == list(
        sorted(additional_ids)
    )


def test_additional_capture_is_sticky_and_conflict_aware() -> None:
    captured = apply_additional_covenant_ban_capture(
        begin_encounter("additional.conflict"), _additional_snapshot()
    )
    conflict = apply_additional_covenant_ban_capture(
        captured.session, _additional_snapshot(_ADDITIONAL_IDS[4:8])
    )

    assert conflict.status is EncounterUpdateStatus.CONFLICT
    assert conflict.session.additional_covenant_ban == captured.session.additional_covenant_ban
    assert conflict.session.additional_covenant_ban_conflict is not None


def test_reference_pack_requires_every_additional_identity_once() -> None:
    image = np.zeros((112, 112, 3), dtype=np.uint8)
    reference = AdditionalCovenantVisualReference(
        _ADDITIONAL_IDS[0], CovenantBanState.DISABLED, image
    )
    with pytest.raises(ValueError, match="exactly every"):
        AdditionalCovenantReferencePack((reference,) * 15)


def test_standard_is_explicitly_unsupported_without_running_matching() -> None:
    assert supports_additional_covenant_ban("difficulty.covenant_latter.standard") is False
    assert supports_additional_covenant_ban("difficulty.covenant_latter.adversity") is True


def test_standard_presentation_marks_ban_unsupported_but_keeps_four_item_progress() -> None:
    session = begin_encounter("additional.standard").model_copy(
        update={
            "captured_difficulty": CapturedDifficulty(
                difficulty_id="difficulty.covenant_latter.standard",
                simulation_code="AC-1",
            )
        }
    )

    view = present_encounter(session, EncounterMapCatalog(definitions=()), locale_id="zh_CN")

    assert view.progress_label == "1 / 4"
    assert view.items[3].complete is False
    assert view.items[3].value == "本模式暂未制作该功能，可忽略"


def test_only_complete_nine_by_six_layout_is_currently_eligible() -> None:
    assert (
        AdditionalCovenantBanObservation(
            AdditionalCovenantBanObservationState.PARTIAL,
            "partial",
            (9,),
            False,
        ).complete_reliable
        is False
    )


def test_surface_selection_ignores_sparse_rows_but_rejects_ambiguous_pairs() -> None:
    assert _select_surface_layout([_row(9, 620), _row(6, 780)]) == ("full_9x6", (0, 1))
    assert _select_surface_layout([_row(1, 500), _row(9, 620), _row(6, 780)]) == (
        "full_9x6",
        (1, 2),
    )
    assert _select_surface_layout([_row(2, 500), _row(9, 620), _row(6, 780)]) == (
        "full_9x6",
        (1, 2),
    )
    assert _select_surface_layout([_row(9, 620), _row(6, 780), _row(9, 800), _row(6, 900)]) is None


def test_surface_selection_leaves_one_row_recognition_to_the_six_slot_lattice() -> None:
    assert _select_surface_layout([_row(6, 780)]) is None
    assert _select_surface_layout([_row(9, 620)]) is None


def test_second_row_only_is_authorized_at_the_lower_hough_boundary_when_crop_is_safe() -> None:
    rows = [_row(5, 700), _row(6, 950)]

    assert _select_surface_layout(rows) is None
    assert additional_ban._candidate_is_detected_in_authorized_surface(rows[1][0])
    assert additional_ban._candidate_has_safe_frame_crop(
        rows[1][0], np.zeros((1080, 1920, 3), dtype=np.uint8)
    )


def test_second_row_only_rejects_a_crop_that_would_be_clipped_by_the_actual_frame() -> None:
    assert not additional_ban._candidate_has_safe_frame_crop(
        (250, 1050, 52), np.zeros((1080, 1920, 3), dtype=np.uint8)
    )


def test_hough_authorization_keeps_the_frozen_search_and_radius_bounds() -> None:
    assert additional_ban._SEARCH == (120, 470, 1660, 520)
    assert additional_ban._LOWER_ROW_RECOVERY_SEARCH == (120, 760, 1160, 320)
    assert not additional_ban._candidate_is_detected_in_authorized_surface((250, 950, 47))
    assert not additional_ban._candidate_is_detected_in_authorized_surface((250, 950, 57))
    assert additional_ban._candidate_is_detected_in_authorized_surface(
        (250, 1020, 52),
        search=additional_ban._LOWER_ROW_RECOVERY_SEARCH,
    )


def test_low_row_recovery_uses_unclipped_canonical_detections_after_primary_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer = object.__new__(AdditionalCovenantBanObserver)
    ids = iter(_ADDITIONAL_IDS[:6])
    saturations = iter((200.0, 190.0, 50.0, 40.0, 30.0, 20.0))
    primary = [
        (298, 657, 52),
        (554, 676, 73),
        (779, 677, 56),
        (967, 673, 71),
        (299, 870, 53),
        (568, 909, 54),
        (761, 905, 71),
        (953, 939, 67),
        (1156, 897, 59),
    ]
    recovery = _six_slot_row_with_trailing_residue(0, 940)
    monkeypatch.setattr(additional_ban, "_circles", lambda _image: primary)
    monkeypatch.setattr(
        additional_ban,
        "_lower_row_recovery_circles",
        lambda _image: recovery,
    )
    monkeypatch.setattr(additional_ban, "_saturation", lambda _crop: next(saturations))
    observer._features = lambda _crop, _state: object()  # type: ignore[method-assign]
    observer._rank = lambda _features: (  # type: ignore[method-assign]
        additional_ban.RankedVisualCandidate(next(ids), 10.0),
        additional_ban.RankedVisualCandidate("other", 0.0),
    )
    frame = type(
        "Frame",
        (),
        {"frame_id": "low-row", "image": np.zeros((1080, 1920, 3), dtype=np.uint8)},
    )()

    observation = observer._observe_surface(frame)  # type: ignore[arg-type]

    assert observation.state is AdditionalCovenantBanObservationState.OBSERVED
    assert observation.row_sizes == (4, 5)
    assert observation.lower_row_recovery_attempted is True
    assert observation.lower_row_recovery_grouped_circle_centers == (tuple(recovery),)
    assert observation.selected_logical_row_source == "lower_row_recovery"
    assert observation.candidate_disabled_covenant_ids == tuple(sorted(_ADDITIONAL_IDS[2:6]))


def test_low_row_recovery_rejects_noncanonical_large_radius_detections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer = object.__new__(AdditionalCovenantBanObserver)
    monkeypatch.setattr(additional_ban, "_circles", lambda _image: _row(4, 670))
    monkeypatch.setattr(
        additional_ban,
        "_lower_row_recovery_circles",
        lambda _image: [(263 + index * 172, 940, 67) for index in range(6)],
    )
    frame = type(
        "Frame",
        (),
        {"frame_id": "false-low-row", "image": np.zeros((1080, 1920, 3), dtype=np.uint8)},
    )()

    observation = observer._observe_surface(frame)  # type: ignore[arg-type]

    assert observation.state is AdditionalCovenantBanObservationState.PARTIAL
    assert observation.lower_row_recovery_attempted is True
    assert observation.logical_row_candidates == ()
    assert observation.selected_logical_row_source is None


def test_low_row_recovery_rejects_two_valid_logical_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer = object.__new__(AdditionalCovenantBanObserver)
    ids = iter(_ADDITIONAL_IDS[:6] * 2)
    saturations = iter((200.0, 190.0, 50.0, 40.0, 30.0, 20.0) * 2)
    monkeypatch.setattr(additional_ban, "_circles", lambda _image: _row(4, 670))
    monkeypatch.setattr(
        additional_ban,
        "_lower_row_recovery_circles",
        lambda _image: [
            *_six_slot_row_with_trailing_residue(0, 850),
            *_six_slot_row_with_trailing_residue(0, 940),
        ],
    )
    monkeypatch.setattr(additional_ban, "_saturation", lambda _crop: next(saturations))
    observer._features = lambda _crop, _state: object()  # type: ignore[method-assign]
    observer._rank = lambda _features: (  # type: ignore[method-assign]
        additional_ban.RankedVisualCandidate(next(ids), 10.0),
        additional_ban.RankedVisualCandidate("other", 0.0),
    )
    frame = type(
        "Frame",
        (),
        {"frame_id": "ambiguous-low-row", "image": np.zeros((1080, 1920, 3), dtype=np.uint8)},
    )()

    observation = observer._observe_surface(frame)  # type: ignore[arg-type]

    assert observation.state is AdditionalCovenantBanObservationState.PARTIAL
    assert observation.reason == "logical_second_row_not_uniquely_complete"
    assert observation.selected_logical_row_source is None


def test_second_row_only_requires_relative_state_polarity_and_glyph_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer = object.__new__(AdditionalCovenantBanObserver)
    ids = iter(_ADDITIONAL_IDS[:6])
    saturations = iter((200.0, 190.0, 50.0, 40.0, 30.0, 20.0))
    monkeypatch.setattr(
        additional_ban,
        "_circles",
        lambda _image: _six_slot_row_with_trailing_residue(0, 780),
    )
    monkeypatch.setattr(additional_ban, "_saturation", lambda _crop: next(saturations))
    observer._features = lambda _crop, _state: object()  # type: ignore[method-assign]
    observer._rank = lambda _features: (  # type: ignore[method-assign]
        additional_ban.RankedVisualCandidate(next(ids), 10.0),
        additional_ban.RankedVisualCandidate("other", 0.0),
    )
    frame = type(
        "Frame",
        (),
        {"frame_id": "second-row", "image": np.zeros((1080, 1920, 3), dtype=np.uint8)},
    )()

    observation = observer._observe_surface(frame)  # type: ignore[arg-type]

    assert observation.state is AdditionalCovenantBanObservationState.OBSERVED
    assert observation.surface_mode == "second_row_only"
    assert observation.candidate_disabled_covenant_ids == tuple(sorted(_ADDITIONAL_IDS[2:6]))


def test_second_row_only_uses_a_valid_lower_boundary_row_despite_a_sparse_neighbor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer = object.__new__(AdditionalCovenantBanObserver)
    ids = iter(_ADDITIONAL_IDS[:6])
    saturations = iter((200.0, 190.0, 50.0, 40.0, 30.0, 20.0))
    monkeypatch.setattr(
        additional_ban,
        "_circles",
        lambda _image: [
            *_row(5, 700),
            *_six_slot_row_with_trailing_residue(0, 950),
        ],
    )
    monkeypatch.setattr(additional_ban, "_saturation", lambda _crop: next(saturations))
    observer._features = lambda _crop, _state: object()  # type: ignore[method-assign]
    observer._rank = lambda _features: (  # type: ignore[method-assign]
        additional_ban.RankedVisualCandidate(next(ids), 10.0),
        additional_ban.RankedVisualCandidate("other", 0.0),
    )
    frame = type(
        "Frame",
        (),
        {"frame_id": "lower-second-row", "image": np.zeros((1080, 1920, 3), dtype=np.uint8)},
    )()

    observation = observer._observe_surface(frame)  # type: ignore[arg-type]

    assert observation.state is AdditionalCovenantBanObservationState.OBSERVED
    assert observation.surface_mode == "second_row_lattice"
    assert observation.selected_row_sizes == (6,)
    assert observation.ignored_row_sizes == (5,)


@pytest.mark.parametrize("missing_index", (0, 2, 5))
def test_five_of_six_geometry_recovers_only_one_missing_slot(missing_index: int) -> None:
    reconstructed = additional_ban._reconstruct_second_row(
        _five_of_six_second_row(missing_index)
    )

    assert reconstructed is not None
    assert tuple(item[0] for item in reconstructed) == tuple(
        263 + index * 172 for index in range(6)
    )


def test_five_of_six_second_row_requires_normal_six_glyph_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer = object.__new__(AdditionalCovenantBanObserver)
    ids = iter(_ADDITIONAL_IDS[:6])
    saturations = iter((200.0, 190.0, 50.0, 40.0, 30.0, 20.0))
    monkeypatch.setattr(
        additional_ban, "_circles", lambda _image: _five_of_six_second_row(2)
    )
    monkeypatch.setattr(additional_ban, "_saturation", lambda _crop: next(saturations))
    observer._features = lambda _crop, _state: object()  # type: ignore[method-assign]
    observer._rank = lambda _features: (  # type: ignore[method-assign]
        additional_ban.RankedVisualCandidate(next(ids), 10.0),
        additional_ban.RankedVisualCandidate("other", 0.0),
    )
    frame = type(
        "Frame",
        (),
        {
            "frame_id": "reconstructed-second-row",
            "image": np.zeros((1080, 1920, 3), dtype=np.uint8),
        },
    )()

    observation = observer._observe_surface(frame)  # type: ignore[arg-type]

    assert observation.state is AdditionalCovenantBanObservationState.OBSERVED
    assert observation.surface_mode == "second_row_reconstructed"
    assert observation.selected_row_sizes == (5,)
    assert observation.candidate_disabled_covenant_ids == tuple(sorted(_ADDITIONAL_IDS[2:6]))


@pytest.mark.parametrize(
    ("rows", "saturations"),
    (
        (
            [_six_slot_row_with_trailing_residue(2, 780)],
            (200.0, 190.0, 50.0, 40.0, 30.0, 20.0),
        ),
        (
            [
                _six_slot_row_with_trailing_residue(0, 650),
                _six_slot_row_with_trailing_residue(0, 850),
            ],
            (220.0,) * 6 + (200.0, 190.0, 50.0, 40.0, 30.0, 20.0),
        ),
        (
            [_five_of_six_second_row(5, 650), _six_slot_row_with_trailing_residue(1, 850)],
            (220.0,) * 6 + (200.0, 190.0, 50.0, 40.0, 30.0, 20.0),
        ),
        (
            [_five_of_six_second_row(0, 650), _five_of_six_second_row(2, 850)],
            (220.0,) * 6 + (200.0, 190.0, 50.0, 40.0, 30.0, 20.0),
        ),
    ),
    ids=("8", "6-6", "5-7", "5-5"),
)
def test_logical_second_row_fit_handles_real_live_row_size_shapes(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[list[tuple[int, int, int]]],
    saturations: tuple[float, ...],
) -> None:
    observer = object.__new__(AdditionalCovenantBanObserver)
    identities = iter(_ADDITIONAL_IDS[:6] * len(rows))
    saturation_values = iter(saturations)
    monkeypatch.setattr(
        additional_ban,
        "_circles",
        lambda _image: [candidate for row in rows for candidate in row],
    )
    monkeypatch.setattr(additional_ban, "_saturation", lambda _crop: next(saturation_values))
    observer._features = lambda _crop, _state: object()  # type: ignore[method-assign]
    observer._rank = lambda _features: (  # type: ignore[method-assign]
        additional_ban.RankedVisualCandidate(next(identities), 10.0),
        additional_ban.RankedVisualCandidate("other", 0.0),
    )
    frame = type(
        "Frame",
        (),
        {"frame_id": "logical-row", "image": np.zeros((1080, 1920, 3), dtype=np.uint8)},
    )()

    observation = observer._observe_surface(frame)  # type: ignore[arg-type]

    assert observation.state is AdditionalCovenantBanObservationState.OBSERVED
    assert observation.candidate_disabled_covenant_ids == tuple(sorted(_ADDITIONAL_IDS[2:6]))
    assert observation.logical_row_candidates
    assert observation.selected_logical_row_centers
    assert len(observation.selected_row_observations) == 6


def test_five_of_six_recovery_rejects_ambiguous_rows_even_when_each_glyph_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer = object.__new__(AdditionalCovenantBanObserver)
    ids = iter(_ADDITIONAL_IDS[:6] * 2)
    saturations = iter((200.0, 190.0, 50.0, 40.0, 30.0, 20.0) * 2)
    monkeypatch.setattr(
        additional_ban,
        "_circles",
        lambda _image: [*_five_of_six_second_row(0, 700), *_five_of_six_second_row(5, 780)],
    )
    monkeypatch.setattr(additional_ban, "_saturation", lambda _crop: next(saturations))
    observer._features = lambda _crop, _state: object()  # type: ignore[method-assign]
    observer._rank = lambda _features: (  # type: ignore[method-assign]
        additional_ban.RankedVisualCandidate(next(ids), 10.0),
        additional_ban.RankedVisualCandidate("other", 0.0),
    )
    frame = type(
        "Frame",
        (),
        {
            "frame_id": "ambiguous-reconstruction",
            "image": np.zeros((1080, 1920, 3), dtype=np.uint8),
        },
    )()

    observation = observer._observe_surface(frame)  # type: ignore[arg-type]

    assert observation.state is AdditionalCovenantBanObservationState.PARTIAL
    assert observation.candidate_disabled_covenant_ids == ()


def test_five_of_six_recovery_rejects_an_inferred_crop_outside_the_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer = object.__new__(AdditionalCovenantBanObserver)
    monkeypatch.setattr(
        additional_ban, "_circles", lambda _image: _five_of_six_second_row(2, 950)
    )
    frame = type(
        "Frame",
        (),
        {"frame_id": "clipped-reconstruction", "image": np.zeros((990, 1920, 3), dtype=np.uint8)},
    )()

    observation = observer._observe_surface(frame)  # type: ignore[arg-type]

    assert observation.state is AdditionalCovenantBanObservationState.PARTIAL
    assert observation.candidate_disabled_covenant_ids == ()


def test_five_of_six_recovery_rejects_duplicate_inferred_glyph_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observer = object.__new__(AdditionalCovenantBanObserver)
    saturations = iter((200.0, 190.0, 50.0, 40.0, 30.0, 20.0))
    monkeypatch.setattr(
        additional_ban, "_circles", lambda _image: _five_of_six_second_row(1)
    )
    monkeypatch.setattr(additional_ban, "_saturation", lambda _crop: next(saturations))
    observer._features = lambda _crop, _state: object()  # type: ignore[method-assign]
    observer._rank = lambda _features: (  # type: ignore[method-assign]
        additional_ban.RankedVisualCandidate(_ADDITIONAL_IDS[0], 10.0),
        additional_ban.RankedVisualCandidate("other", 0.0),
    )
    frame = type(
        "Frame",
        (),
        {
            "frame_id": "duplicate-reconstruction",
            "image": np.zeros((1080, 1920, 3), dtype=np.uint8),
        },
    )()

    observation = observer._observe_surface(frame)  # type: ignore[arg-type]

    assert observation.state is AdditionalCovenantBanObservationState.PARTIAL
    assert observation.candidate_disabled_covenant_ids == ()


def test_two_identical_candidate_sets_are_required_before_controller_capture() -> None:
    controller = LiveEncounterPreviewController()
    controller._session = begin_encounter("additional.debounce")  # noqa: SLF001
    observation = AdditionalCovenantBanObservation(
        AdditionalCovenantBanObservationState.OBSERVED,
        "candidate",
        (9, 6),
        True,
        candidate_disabled_covenant_ids=tuple(sorted(_ADDITIONAL_IDS[:4])),
    )

    controller._apply_additional_covenant_ban_observation(  # noqa: SLF001
        observation,
        source=AdditionalCovenantBanCaptureSource.INITIAL_INFO_VISUAL,
        returned=False,
    )
    assert controller.session is not None
    assert controller.session.additional_covenant_ban is None
    controller._apply_additional_covenant_ban_observation(  # noqa: SLF001
        observation,
        source=AdditionalCovenantBanCaptureSource.INITIAL_INFO_VISUAL,
        returned=False,
    )
    assert controller.session is not None
    assert controller.session.additional_covenant_ban is not None
    assert (
        AdditionalCovenantBanObservation(
            AdditionalCovenantBanObservationState.UNRESOLVED,
            "six-only",
            (6,),
            True,
        ).complete_reliable
        is False
    )


def test_additional_diagnostics_explain_logical_row_geometry_without_frame_pixels() -> None:
    centers = tuple(_six_slot_row_with_trailing_residue(0, 850))
    observations = tuple(
        additional_ban.AdditionalCovenantIdentityObservation(
            index,
            center[:2],
            200.0 if index <= 2 else 40.0,
            (
                additional_ban.RankedVisualCandidate(_ADDITIONAL_IDS[index - 1], 10.0),
                additional_ban.RankedVisualCandidate("other", 0.0),
            ),
        )
        for index, center in enumerate(centers, start=1)
    )
    diagnostic = additional_ban.AdditionalLogicalRowCandidateDiagnostic(
        source_row_index=1,
        detected_centers=centers[:-1],
        completed_centers=centers,
        matched_slot_count=5,
        maximum_x_residual=2.0,
        inferred_missing_slot_index=5,
        ignored_detection_count=1,
        detection_source="lower_row_recovery",
        rejection_reason=None,
        identity_rankings=tuple(item.ranking for item in observations),
    )
    controller = LiveEncounterPreviewController()
    controller._latest_additional_covenant_ban = AdditionalCovenantBanObservation(  # noqa: SLF001
        AdditionalCovenantBanObservationState.OBSERVED,
        "diagnostic",
        (5, 7),
        True,
        target_observations=observations[2:],
        candidate_disabled_covenant_ids=tuple(sorted(_ADDITIONAL_IDS[2:6])),
        surface_mode="second_row_reconstructed",
        grouped_circle_centers=(centers[:5], centers),
        logical_row_candidates=(diagnostic,),
        selected_logical_row_centers=centers,
        selected_row_observations=observations,
        extra_detections_ignored=True,
        lower_row_recovery_attempted=True,
        lower_row_recovery_grouped_circle_centers=(centers,),
        selected_logical_row_source="lower_row_recovery",
    )

    payload = json.loads(controller.diagnostic_json())

    assert payload["additional_grouped_circle_centers"]
    assert payload["additional_lower_row_recovery_attempted"] is True
    assert payload["additional_lower_row_recovery_grouped_circle_centers"]
    assert payload["additional_selected_logical_row_source"] == "lower_row_recovery"
    assert (
        payload["additional_logical_row_candidates"][0]["detection_source"]
        == "lower_row_recovery"
    )
    assert payload["additional_logical_row_candidates"][0]["matched_slot_count"] == 5
    assert payload["additional_logical_row_candidates"][0]["inferred_missing_slot_index"] == 5
    assert len(payload["additional_logical_row_candidates"][0]["identity_top_two"]) == 6
    assert len(payload["additional_six_identity_top_two"]) == 6
    assert payload["additional_extra_detections_ignored"] is True
