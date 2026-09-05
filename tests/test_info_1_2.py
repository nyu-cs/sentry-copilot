from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

import sentry_copilot.encounter.info_1_2_catalog as info_1_2_catalog
from sentry_copilot.encounter.catalog import EncounterMapCatalog
from sentry_copilot.encounter.info_1_2_catalog import (
    PRIVATE_INFO_DIFFICULTY_REFERENCE_REGISTRATIONS,
    calibrated_info_difficulty_reference_registrations,
    load_info_1_2_resources,
)
from sentry_copilot.encounter.lifecycle import begin_encounter
from sentry_copilot.encounter.models import (
    BossDefinition,
    DifficultyDefinition,
    EnemyCategoryDefinition,
    LocalizedText,
)
from sentry_copilot.encounter.session import apply_boss_capture, apply_enemy_type_capture
from sentry_copilot.services.live_encounter_preview import (
    LiveEncounterPreviewController,
    _sanitize_reference_load_failure,
)
from sentry_copilot.vision.info_1_2 import (
    CALIBRATED_INFO_DIFFICULTY_IDS,
    INFO_DIFFICULTY_IDS,
    INFO_DIFFICULTY_ROI,
    KNOWN_DIFFICULTY_IDS,
    EnemySlotLayout,
    EnemyVisualReference,
    Info12Observation,
    Info12ReferencePack,
    Info12State,
    RankedVisualCandidate,
    VisualReference,
    _rank_frozen_color_difficulty,
    classify_enemy_slot_layout,
    crop_info_difficulty_reference,
)


def _catalog() -> EncounterMapCatalog:
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
    )


def _genuine_initial_info(
    frame_id: str,
    *,
    boss_ranking: tuple[RankedVisualCandidate, ...] = (),
    difficulty_ranking: tuple[RankedVisualCandidate, ...] = (),
) -> Info12Observation:
    """Build a valid initial INFO fixture with one reliable Enemy identity."""

    return Info12Observation(
        Info12State.PRESENT,
        frame_id,
        0.9,
        boss_ranking=boss_ranking,
        enemy_rankings=(
            (
                RankedVisualCandidate("enemy.0", 0.9),
                RankedVisualCandidate("enemy.1", 0.5),
            ),
            (),
        ),
        enemy_slot_layout=EnemySlotLayout.TWO_SLOT,
        difficulty_ranking=difficulty_ranking,
    )


def test_boss_and_complete_distinct_enemy_capture_are_sticky() -> None:
    catalog = _catalog()
    session = begin_encounter("info:one")
    boss = apply_boss_capture(session, "boss.0", catalog)
    partial = apply_enemy_type_capture(boss.session, ("enemy.0", "enemy.0", "enemy.1"), catalog)
    complete = apply_enemy_type_capture(boss.session, ("enemy.0", "enemy.1", "enemy.2"), catalog)
    conflict = apply_boss_capture(complete.session, "boss.1", catalog)

    two = apply_enemy_type_capture(boss.session, ("enemy.0", "enemy.1"), catalog)
    assert boss.session.ordinary_progress_count == 1
    assert two.session.enemy_type_ids == ("enemy.0", "enemy.1")
    assert partial.session.enemy_type_ids is None
    assert complete.session.ordinary_progress_count == 2
    assert conflict.session.boss_id == "boss.0"
    assert conflict.session.boss_conflict is not None


def test_enemy_capture_rejects_invalid_cardinality_duplicates_and_unknown_ids() -> None:
    catalog = _catalog()
    session = begin_encounter("info:invalid")
    for values in (
        (),
        ("enemy.0",),
        ("enemy.0", "enemy.0"),
        ("enemy.0", "enemy.1", "enemy.2", "enemy.3"),
        ("unknown", "enemy.1"),
    ):
        assert apply_enemy_type_capture(session, values, catalog).status.value == "unresolved"


def test_ranked_observation_exposes_only_safe_boss_and_enemy_candidates() -> None:
    safe = (RankedVisualCandidate("boss.0", 0.40), RankedVisualCandidate("boss.1", 0.35))
    weak = (RankedVisualCandidate("boss.0", 0.31), RankedVisualCandidate("boss.1", 0.30))
    enemies = tuple(
        (RankedVisualCandidate(f"enemy.{i}", 0.80), RankedVisualCandidate("other", 0.50))
        for i in range(3)
    )
    assert (
        Info12Observation(Info12State.PRESENT, "frame", 0.9, safe, enemies).reliable_boss_id
        == "boss.0"
    )
    assert (
        Info12Observation(Info12State.PRESENT, "frame", 0.9, weak, enemies).reliable_boss_id is None
    )
    assert Info12Observation(
        Info12State.PRESENT,
        "frame",
        0.9,
        safe,
        enemies,
        EnemySlotLayout.THREE_SLOT,
    ).reliable_enemy_ids == ("enemy.0", "enemy.1", "enemy.2")
    assert (
        Info12Observation(Info12State.PRESENT, "frame", 0.9, safe, enemies).reliable_enemy_ids == ()
    )


def test_difficulty_reference_crop_matches_the_calibrated_query_geometry() -> None:
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    frame[
        INFO_DIFFICULTY_ROI.y : INFO_DIFFICULTY_ROI.bottom,
        INFO_DIFFICULTY_ROI.x : INFO_DIFFICULTY_ROI.right,
    ] = 17

    cropped = crop_info_difficulty_reference(frame)

    assert cropped.shape == (INFO_DIFFICULTY_ROI.height, INFO_DIFFICULTY_ROI.width, 3)
    assert np.all(cropped == 17)


def test_enemy_slot_layout_threshold_boundaries_are_exact() -> None:
    assert classify_enemy_slot_layout(0.01) is EnemySlotLayout.TWO_SLOT
    assert classify_enemy_slot_layout(0.010001) is EnemySlotLayout.UNRESOLVED
    assert classify_enemy_slot_layout(0.099999) is EnemySlotLayout.UNRESOLVED
    assert classify_enemy_slot_layout(0.10) is EnemySlotLayout.THREE_SLOT


def test_info_reference_pack_requires_all_four_supported_difficulty_ids() -> None:
    boss = VisualReference("boss.0", np.zeros((8, 8, 3), dtype=np.uint8))
    enemy = EnemyVisualReference("enemy.0", np.zeros((8, 8, 4), dtype=np.uint8))
    difficulties = tuple(
        VisualReference(identity_id, np.zeros((8, 8, 3), dtype=np.uint8))
        for identity_id in INFO_DIFFICULTY_IDS
    )
    Info12ReferencePack(
        np.zeros((8, 8, 3), dtype=np.uint8),
        tuple(replace(boss, identity_id=f"boss.{index}") for index in range(7)),
        tuple(replace(enemy, identity_id=f"enemy.{index}") for index in range(7)),
        difficulties,
    )
    Info12ReferencePack(
        np.zeros((8, 8, 3), dtype=np.uint8),
        tuple(replace(boss, identity_id=f"boss.{index}") for index in range(7)),
        tuple(replace(enemy, identity_id=f"enemy.{index}") for index in range(7)),
        difficulties + (difficulties[-1],),
    )
    with pytest.raises(ValueError, match="all four supported identities"):
        Info12ReferencePack(
            np.zeros((8, 8, 3), dtype=np.uint8),
            tuple(replace(boss, identity_id=f"boss.{index}") for index in range(7)),
            tuple(replace(enemy, identity_id=f"enemy.{index}") for index in range(7)),
            difficulties[:2],
        )


def test_ultimate_is_known_and_present_in_the_frozen_visual_reference_set() -> None:
    ultimate_id = "difficulty.covenant_latter.ultimate"
    registrations = calibrated_info_difficulty_reference_registrations()

    assert ultimate_id in KNOWN_DIFFICULTY_IDS
    assert CALIBRATED_INFO_DIFFICULTY_IDS == INFO_DIFFICULTY_IDS
    assert ultimate_id in INFO_DIFFICULTY_IDS
    assert {item.difficulty_id for item in registrations} == set(INFO_DIFFICULTY_IDS)
    assert next(
        item
        for item in PRIVATE_INFO_DIFFICULTY_REFERENCE_REGISTRATIONS
        if item.difficulty_id == ultimate_id
    ).relative_path is not None


def test_declared_loader_uses_all_frozen_physical_references(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    loaded_paths: list[Path] = []

    def fake_load(path: Path) -> np.ndarray:
        loaded_paths.append(path)
        return np.zeros((1080, 1920, 3), dtype=np.uint8)

    monkeypatch.setattr(info_1_2_catalog, "load_bgr_image", fake_load)

    references = info_1_2_catalog._load_declared_difficulty_references(tmp_path)

    assert {item.identity_id for item in references} == set(INFO_DIFFICULTY_IDS)
    assert len(references) == 6
    assert len(loaded_paths) == 6
    assert any("ultimate" in path.as_posix() for path in loaded_paths)
    assert all(item.image.shape == (70, 220, 3) for item in references)


def _difficulty_image(seed: int) -> np.ndarray:
    image = np.zeros((70, 220, 3), dtype=np.uint8)
    image[:, :178] = np.array(((seed * 31) % 255, 255, 90 + seed * 19), dtype=np.uint8)
    return image


def test_difficulty_ranking_collapses_variants_into_logical_identities() -> None:
    standard = _difficulty_image(1)
    adversity = _difficulty_image(2)
    old_deadland = _difficulty_image(3)
    alternate_deadland = _difficulty_image(4)
    references = (
        VisualReference(INFO_DIFFICULTY_IDS[0], standard),
        VisualReference(INFO_DIFFICULTY_IDS[1], adversity),
        VisualReference(INFO_DIFFICULTY_IDS[2], old_deadland),
        VisualReference(INFO_DIFFICULTY_IDS[2], alternate_deadland),
    )

    without_variant = _rank_frozen_color_difficulty(alternate_deadland, references[:-1])
    ranking = _rank_frozen_color_difficulty(alternate_deadland, references)

    assert Info12Observation(
        Info12State.PRESENT,
        "existing",
        0.9,
        difficulty_ranking=without_variant,
    ).difficulty_candidate_id == INFO_DIFFICULTY_IDS[2]
    assert ranking[0].identity_id == INFO_DIFFICULTY_IDS[2]
    assert {item.identity_id for item in ranking} == {
        INFO_DIFFICULTY_IDS[0],
        INFO_DIFFICULTY_IDS[1],
        INFO_DIFFICULTY_IDS[2],
    }
    assert len(ranking) == 3
    assert ranking[0].score == pytest.approx(1.0)
    assert ranking[0].identity_id != ranking[1].identity_id
    assert Info12Observation(
        Info12State.PRESENT,
        "variant",
        0.9,
        difficulty_ranking=ranking,
    ).difficulty_candidate_id == INFO_DIFFICULTY_IDS[2]




def test_single_template_difficulty_ranking_keeps_existing_logical_semantics() -> None:
    references = tuple(
        VisualReference(identity_id, _difficulty_image(index))
        for index, identity_id in enumerate(INFO_DIFFICULTY_IDS)
    )

    standard = _rank_frozen_color_difficulty(references[0].image, references)
    adversity = _rank_frozen_color_difficulty(references[1].image, references)

    assert {item.identity_id for item in standard} == set(INFO_DIFFICULTY_IDS)
    assert standard[0].score == pytest.approx(1.0)
    assert adversity[0].identity_id == INFO_DIFFICULTY_IDS[1]
    assert adversity[0].score == pytest.approx(1.0, abs=1e-5)


def test_color_difficulty_candidate_has_no_legacy_grayscale_acceptance_gate() -> None:
    observation = Info12Observation(
        Info12State.PRESENT,
        "low-color-score",
        0.9,
        difficulty_ranking=(
            RankedVisualCandidate(INFO_DIFFICULTY_IDS[3], 0.10),
            RankedVisualCandidate(INFO_DIFFICULTY_IDS[0], 0.09),
        ),
    )

    assert observation.difficulty_candidate_id == INFO_DIFFICULTY_IDS[3]


@pytest.mark.parametrize(
    ("boss_content", "expected_message"),
    (
        ("ordinary_boss_pool: [", "INFO catalog YAML is invalid"),
        ("ordinary_boss_pool:\n  - names: {}\n", "INFO catalog is missing a required record field"),
    ),
)
def test_malformed_catalogs_follow_the_visible_info_resource_failure_path(
    tmp_path: Path,
    boss_content: str,
    expected_message: str,
) -> None:
    boss_catalog = tmp_path / "boss.yaml"
    enemy_catalog = tmp_path / "enemy.yaml"
    boss_catalog.write_text(boss_content, encoding="utf-8")
    enemy_catalog.write_text("enemy_categories: []\n", encoding="utf-8")

    with pytest.raises(ValueError, match=expected_message) as raised:
        load_info_1_2_resources(
            boss_catalog,
            enemy_catalog,
            tmp_path / "anchor.png",
            tmp_path / "bosses",
            tmp_path / "enemies",
            _catalog(),
        )

    failure = _sanitize_reference_load_failure(raised.value)
    controller = LiveEncounterPreviewController(info_reference_failure=failure)
    assert controller.snapshot().status.value == "info_references_unavailable"
    assert controller.snapshot().reason == "INFO reference resources are invalid"


def test_initial_info_starts_once() -> None:
    controller = LiveEncounterPreviewController(_UnusedOcr(), catalog=_catalog())
    info = _genuine_initial_info("info")
    controller.apply_info_1_2_observation(info)
    first = controller.session
    controller.apply_info_1_2_observation(info)
    assert first is not None and controller.session == first


def test_non_info_frame_resets_only_pending_boss_confirmation() -> None:
    controller = LiveEncounterPreviewController(_UnusedOcr(), catalog=_catalog())
    ranking = (RankedVisualCandidate("boss.0", 0.40), RankedVisualCandidate("boss.1", 0.35))
    present = _genuine_initial_info("present", boss_ranking=ranking)
    absent = Info12Observation(Info12State.ABSENT, "absent", 0.1)
    controller.apply_info_1_2_observation(present)
    controller.apply_info_1_2_observation(present)
    controller.apply_info_1_2_observation(absent)
    controller.apply_info_1_2_observation(present)
    assert controller.session is not None and controller.session.boss_id is None
    controller.apply_info_1_2_observation(present)
    controller.apply_info_1_2_observation(present)
    assert controller.session is not None and controller.session.boss_id == "boss.0"


def test_info_difficulty_requires_two_consecutive_present_observations() -> None:
    base = _catalog()
    catalog = EncounterMapCatalog(
        definitions=(),
        difficulties=(
            DifficultyDefinition(
                difficulty_id="difficulty.covenant_latter.deadland",
                simulation_codes=("AC-3",),
                names=(LocalizedText(locale_id="en", text="Deadland"),),
            ),
        ),
        bosses=base.bosses,
        enemy_categories=base.enemy_categories,
    )
    controller = LiveEncounterPreviewController(_UnusedOcr(), catalog=catalog)
    ranking = (
        RankedVisualCandidate("difficulty.covenant_latter.deadland", 0.9),
        RankedVisualCandidate("other", 0.6),
    )
    present = _genuine_initial_info("info", difficulty_ranking=ranking)
    controller.apply_info_1_2_observation(present)
    controller.apply_info_1_2_observation(Info12Observation(Info12State.ABSENT, "gap", 0.1))
    controller.apply_info_1_2_observation(present)
    assert controller.session is not None and controller.session.captured_difficulty is None
    controller.apply_info_1_2_observation(present)
    assert controller.session is not None
    assert controller.session.captured_difficulty is not None
    assert controller.session.captured_difficulty.observed_label is None


def test_new_encounter_resets_pending_info_difficulty_confirmation() -> None:
    base = _catalog()
    catalog = EncounterMapCatalog(
        definitions=(),
        difficulties=(
            DifficultyDefinition(
                difficulty_id="difficulty.covenant_latter.deadland",
                simulation_codes=("AC-3",),
                names=(LocalizedText(locale_id="en", text="Deadland"),),
            ),
        ),
        bosses=base.bosses,
        enemy_categories=base.enemy_categories,
    )
    controller = LiveEncounterPreviewController(_UnusedOcr(), catalog=catalog)
    ranking = (
        RankedVisualCandidate("difficulty.covenant_latter.deadland", 0.9),
        RankedVisualCandidate("other", 0.6),
    )
    present = _genuine_initial_info("info", difficulty_ranking=ranking)
    controller.apply_info_1_2_observation(present)
    controller._end_watcher = replace(controller._end_watcher, ended=True)

    controller.apply_info_1_2_observation(present)
    assert controller.session is not None and controller.session.captured_difficulty is None
    controller.apply_info_1_2_observation(present)
    assert controller.session is not None
    assert controller.session.captured_difficulty is not None


class _UnusedOcr:
    async def recognize(self, image: object, *, language_tag: str) -> object:
        raise AssertionError("INFO lifecycle test must not use OCR")
