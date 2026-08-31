from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
import yaml

from sentry_copilot.capture.frame_source import Frame, FrameSourceType
from sentry_copilot.encounter.catalog import JP_MUMU_ENCOUNTER_MAP_CATALOG, EncounterMapCatalog
from sentry_copilot.encounter.lifecycle import begin_encounter
from sentry_copilot.encounter.models import (
    BossDefinition,
    CapturedDifficulty,
    CapturedMap,
    DifficultyCaptureSource,
    DifficultyDefinition,
    EncounterCaptureItem,
    EncounterMapDefinition,
    EnemyCategoryDefinition,
    LocalizedText,
    MapKnowledgeCategory,
    MapKnowledgeEntry,
)
from sentry_copilot.encounter.presentation import present_encounter
from sentry_copilot.encounter.session import (
    EncounterUpdateStatus,
    apply_operation_difficulty_observation,
)
from sentry_copilot.vision.ocr import OcrBackend, OcrBackendReading
from sentry_copilot.vision.operation_difficulty import (
    JP_MUMU_OPERATION_DIFFICULTY_ROI,
    JP_MUMU_OPERATION_SIMULATION_CODE_ROI,
    OperationDifficultyObservation,
    OperationDifficultyState,
    observe_jp_mumu_operation_difficulty,
)
from sentry_copilot.vision.viewport import ContentViewport, PixelRoi


class _OperationOcrBackend:
    async def recognize(self, image: np.ndarray, *, language_tag: str) -> OcrBackendReading:
        assert language_tag == "ja-JP"
        return OcrBackendReading("AC 3 」" if image.shape[1] == 480 else "死 地")


class _CodeAndDifficultyBackend:
    def __init__(self, code: str, difficulty: str) -> None:
        self.code = code
        self.difficulty = difficulty

    async def recognize(self, image: np.ndarray, *, language_tag: str) -> OcrBackendReading:
        return OcrBackendReading(self.code if image.shape[1] == 480 else self.difficulty)


def _frame() -> Frame:
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    image[500:640, 720:1200] = (255, 255, 255)
    return Frame(
        frame_id="operation:0",
        frame_index=0,
        processed_at=datetime(2026, 8, 28, tzinfo=UTC),
        source_timestamp=None,
        source_type=FrameSourceType.IMAGE_SEQUENCE,
        source_id="synthetic",
        source_reference="synthetic:operation",
        width=1920,
        height=1080,
        image=image,
    )


def _observe(frame: Frame, backend: OcrBackend) -> OperationDifficultyObservation:
    return asyncio.run(
        observe_jp_mumu_operation_difficulty(frame, ContentViewport.full_frame(frame), backend)
    )


def test_operation_difficulty_observer_normalizes_ac_3_and_preserves_provenance() -> None:
    frame = _frame()
    observation = _observe(frame, _OperationOcrBackend())

    assert observation.state is OperationDifficultyState.OBSERVED
    assert observation.simulation_code == "AC-3"
    assert observation.difficulty_id == "difficulty.covenant_latter.deadland"
    assert observation.observed_difficulty == "死地"
    assert observation.simulation_code_ocr is not None
    assert observation.simulation_code_ocr.pixel_bounds == JP_MUMU_OPERATION_SIMULATION_CODE_ROI
    assert observation.difficulty_ocr is not None
    assert observation.difficulty_ocr.pixel_bounds == JP_MUMU_OPERATION_DIFFICULTY_ROI
    assert observation.frame_id == frame.frame_id


def test_operation_difficulty_observer_is_conservative_for_unknown_code_or_label() -> None:
    frame = _frame()
    unknown_code = _observe(frame, _CodeAndDifficultyBackend("not a stage", "死地"))
    unknown_label = _observe(frame, _CodeAndDifficultyBackend("AC-3", "未校准"))
    wrong_viewport = ContentViewport(
        frame_id=frame.frame_id,
        frame_width=1920,
        frame_height=1080,
        pixel_roi=PixelRoi(x=1, y=0, width=1919, height=1080),
    )
    wrong_layout = asyncio.run(
        observe_jp_mumu_operation_difficulty(frame, wrong_viewport, _OperationOcrBackend())
    )

    assert unknown_code.state is OperationDifficultyState.UNRESOLVED
    assert unknown_label.state is OperationDifficultyState.OBSERVED
    assert unknown_label.simulation_code == "AC-3"
    assert unknown_label.difficulty_id is None
    assert wrong_layout.state is OperationDifficultyState.UNRESOLVED


def test_operation_difficulty_captures_without_a_battlefield_or_progress() -> None:
    observed = _observe(_frame(), _OperationOcrBackend())
    captured = apply_operation_difficulty_observation(
        begin_encounter("encounter.synthetic.1"), observed, JP_MUMU_ENCOUNTER_MAP_CATALOG
    )
    repeated = apply_operation_difficulty_observation(
        captured.session, observed, JP_MUMU_ENCOUNTER_MAP_CATALOG
    )
    weak = apply_operation_difficulty_observation(
        repeated.session,
        _observe(_frame(), _CodeAndDifficultyBackend("AC-3", "未校准")),
        JP_MUMU_ENCOUNTER_MAP_CATALOG,
    )

    assert captured.status is EncounterUpdateStatus.CAPTURED
    assert captured.session.captured_map is None
    assert captured.session.captured_difficulty == CapturedDifficulty(
        difficulty_id="difficulty.covenant_latter.deadland",
        simulation_code="AC-3",
        observed_label="死地",
        capture_source=DifficultyCaptureSource.OPERATION_OCR,
    )
    assert captured.session.ordinary_progress_count == 1
    assert repeated.status is EncounterUpdateStatus.PRESERVED
    assert weak.status is EncounterUpdateStatus.UNRESOLVED
    assert weak.session.captured_difficulty == captured.session.captured_difficulty


def test_contradictory_validated_difficulty_preserves_first_capture_and_conflict() -> None:
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
    first = replace(
        _observe(_frame(), _OperationOcrBackend()),
        difficulty_id="difficulty.synthetic.a",
        observed_difficulty="A",
    )
    second = replace(
        first,
        simulation_code="AC-4",
        difficulty_id="difficulty.synthetic.b",
        observed_difficulty="B",
    )
    initial = apply_operation_difficulty_observation(
        begin_encounter("encounter.synthetic.conflict"), first, catalog
    )
    result = apply_operation_difficulty_observation(initial.session, second, catalog)

    assert result.status is EncounterUpdateStatus.CONFLICT
    assert result.session.captured_difficulty == initial.session.captured_difficulty
    assert result.session.difficulty_conflict is not None


def test_presentation_keeps_map_and_difficulty_independent() -> None:
    catalog = EncounterMapCatalog(
        definitions=(
            EncounterMapDefinition(
                map_id="map.synthetic.battlefield",
                map_code="BF-1",
                names=(LocalizedText(locale_id="zh_CN", text="合成地图"),),
                knowledge_entries=(
                    MapKnowledgeEntry(
                        entry_id="fact.synthetic",
                        category=MapKnowledgeCategory.TERRAIN,
                        titles=(LocalizedText(locale_id="zh_CN", text="特殊地形"),),
                        descriptions=(LocalizedText(locale_id="zh_CN", text="仅用于测试"),),
                    ),
                ),
            ),
        ),
        difficulties=(
            DifficultyDefinition(
                difficulty_id="difficulty.synthetic.deadland",
                simulation_codes=("AC-3",),
                names=(
                    LocalizedText(locale_id="zh_CN", text="死地"),
                    LocalizedText(locale_id="en", text="Deadland"),
                ),
            ),
        ),
    )
    difficulty_only = begin_encounter("encounter.difficulty").model_copy(
        update={
            "captured_difficulty": CapturedDifficulty(
                difficulty_id="difficulty.synthetic.deadland",
                simulation_code="AC-3",
                observed_label="死地",
            )
        }
    )
    view = present_encounter(difficulty_only, catalog, locale_id="zh_CN")
    assert view.items[0].complete is True
    assert view.items[0].value == "死地"
    assert view.items[-1].value == "本版本暂未支持"
    assert view.progress_label == "1 / 5"
    assert view.difficulty_value == "死地"
    english_view = present_encounter(difficulty_only, catalog, locale_id="en")
    assert english_view.title == "Encounter Intel"
    assert english_view.items[0].label == "Difficulty"
    assert english_view.items[0].value == "Deadland"
    assert english_view.items[1].value == "Not captured"
    assert english_view.items[-1].value == "Not supported in this preview"

    with_map = difficulty_only.model_copy(
        update={"captured_map": CapturedMap(map_id="map.synthetic.battlefield", map_code="BF-1")}
    )
    map_view = present_encounter(with_map, catalog, locale_id="zh_CN")
    assert map_view.items[-1].value == "BF-1 · 合成地图"
    assert map_view.progress_label == "2 / 5"


def test_jp_catalog_does_not_define_ac_3_as_a_battlefield() -> None:
    assert JP_MUMU_ENCOUNTER_MAP_CATALOG.by_code("AC-3") is None
    definition = JP_MUMU_ENCOUNTER_MAP_CATALOG.difficulty_by_simulation_code("AC-3")
    assert definition is not None
    assert definition.difficulty_id == "difficulty.covenant_latter.deadland"


def test_initial_presentation_marks_difficulty_as_not_captured_not_unsupported() -> None:
    catalog = EncounterMapCatalog(definitions=())

    zh_view = present_encounter(begin_encounter("encounter.initial"), catalog, locale_id="zh_CN")
    en_view = present_encounter(begin_encounter("encounter.initial"), catalog, locale_id="en")

    assert zh_view.progress_label == "0 / 5"
    assert zh_view.items[0].label == "难度"
    assert zh_view.items[0].value == "尚未识别"
    assert zh_view.items[3].value == "本版本暂未支持"
    assert en_view.items[0].label == "Difficulty"
    assert en_view.items[0].value == "Not captured"
    assert en_view.items[3].value == "Not supported in this preview"


def test_presentation_has_exactly_one_difficulty_in_the_five_ordinary_rows() -> None:
    view = present_encounter(
        begin_encounter("encounter.rows"), EncounterMapCatalog(definitions=()), locale_id="en"
    )

    assert [item.item for item in view.items] == [
        EncounterCaptureItem.DIFFICULTY,
        EncounterCaptureItem.BOSS,
        EncounterCaptureItem.ENEMY_TYPES,
        EncounterCaptureItem.BANNED_COVENANTS,
        EncounterCaptureItem.MAP,
    ]
    assert sum(item.item is EncounterCaptureItem.DIFFICULTY for item in view.items) == 1


def test_public_info_catalog_english_labels_drive_presentation_without_chinese_fallback() -> None:
    root = Path("data/catalogs/covenant_latter")
    boss_document = yaml.safe_load(
        (root / "boss_catalog_covenant_latter_draft.yaml").read_text(encoding="utf-8")
    )
    enemy_document = yaml.safe_load(
        (root / "enemy_category_catalog_covenant_latter_draft.yaml").read_text(encoding="utf-8")
    )
    assert isinstance(boss_document, dict)
    assert isinstance(enemy_document, dict)
    bosses = tuple(
        BossDefinition(
            boss_id=entry["boss_id"],
            names=tuple(
                LocalizedText(locale_id=locale, text=text)
                for locale, text in entry["names"].items()
            ),
        )
        for entry in boss_document["ordinary_boss_pool"]
    )
    enemies = tuple(
        EnemyCategoryDefinition(
            enemy_category_id=entry["enemy_category_id"],
            names=tuple(
                LocalizedText(locale_id=locale, text=text)
                for locale, text in entry["names"].items()
            ),
        )
        for entry in enemy_document["enemy_categories"]
    )
    catalog = EncounterMapCatalog(
        definitions=(),
        difficulties=JP_MUMU_ENCOUNTER_MAP_CATALOG.difficulties,
        bosses=bosses,
        enemy_categories=enemies,
    )
    session = begin_encounter("encounter.project-english-labels").model_copy(
        update={
            "boss_id": "boss.covenant_latter.quintus",
            "enemy_type_ids": (
                "enemy_type.covenant_latter.flying",
                "enemy_type.covenant_latter.hit_count",
            ),
            "captured_difficulty": CapturedDifficulty(
                difficulty_id="difficulty.covenant_latter.deadland",
                simulation_code="AC-3",
            ),
        }
    )

    english = present_encounter(session, catalog, locale_id="en")
    chinese = present_encounter(session, catalog, locale_id="zh_CN")
    english_values = {item.item: item.value for item in english.items}
    chinese_values = {item.item: item.value for item in chinese.items}

    assert english_values[EncounterCaptureItem.DIFFICULTY] == "Deadland"
    assert english_values[EncounterCaptureItem.BOSS] == "Quintus"
    assert english_values[EncounterCaptureItem.ENEMY_TYPES] == "Flying / Hit Count"
    assert chinese_values[EncounterCaptureItem.BOSS] == "盐风主教昆图斯"
    assert chinese_values[EncounterCaptureItem.ENEMY_TYPES] == "飞行 / 频次"


def test_all_project_english_info_labels_are_declared_and_unknowns_keep_safe_fallback() -> None:
    root = Path("data/catalogs/covenant_latter")
    boss_document = yaml.safe_load(
        (root / "boss_catalog_covenant_latter_draft.yaml").read_text(encoding="utf-8")
    )
    enemy_document = yaml.safe_load(
        (root / "enemy_category_catalog_covenant_latter_draft.yaml").read_text(encoding="utf-8")
    )
    assert isinstance(boss_document, dict)
    assert isinstance(enemy_document, dict)
    boss_names = {
        entry["boss_id"]: entry["names"]["en"]
        for entry in boss_document["ordinary_boss_pool"]
    }
    enemy_names = {
        entry["enemy_category_id"]: entry["names"]["en"]
        for entry in enemy_document["enemy_categories"]
    }
    assert boss_names == {
        "boss.covenant_latter.hypothetical_armor": "Hypothetical Armor",
        "boss.covenant_latter.hypothetical_gun": "Hypothetical Gun",
        "boss.covenant_latter.hypothetical_pipe": "Hypothetical Pipe",
        "boss.covenant_latter.quintus": "Quintus",
        "boss.covenant_latter.lucian": "Lucian",
        "boss.covenant_latter.alistair": "Alistair",
        "boss.covenant_latter.sami_will": "Sami's Will",
    }
    assert enemy_names == {
        "enemy_type.covenant_latter.exceptional": "Exceptional",
        "enemy_type.covenant_latter.flying": "Flying",
        "enemy_type.covenant_latter.hit_count": "Hit Count",
        "enemy_type.covenant_latter.elemental": "Elemental",
        "enemy_type.covenant_latter.persistent": "Persistent",
        "enemy_type.covenant_latter.stealth": "Stealth",
        "enemy_type.covenant_latter.refraction": "Refraction",
    }
    catalog = EncounterMapCatalog(
        definitions=(),
        bosses=(
            BossDefinition(
                boss_id="boss.synthetic.unlocalized",
                names=(LocalizedText(locale_id="zh_CN", text="仅中文"),),
            ),
        ),
    )
    session = begin_encounter("encounter.unlocalized").model_copy(
        update={"boss_id": "boss.synthetic.unlocalized"}
    )
    assert present_encounter(session, catalog, locale_id="en").items[1].value == "仅中文"


@pytest.mark.parametrize(
    ("difficulty_id", "simulation_code", "expected"),
    (
        ("difficulty.covenant_latter.standard", "AC-1", "Standard"),
        ("difficulty.covenant_latter.adversity", "AC-2", "Adversity"),
        ("difficulty.covenant_latter.deadland", "AC-3", "Deadland"),
    ),
)
def test_project_difficulty_english_display_names_remain_deliberate(
    difficulty_id: str,
    simulation_code: str,
    expected: str,
) -> None:
    session = begin_encounter(f"encounter.{simulation_code}").model_copy(
        update={
            "captured_difficulty": CapturedDifficulty(
                difficulty_id=difficulty_id,
                simulation_code=simulation_code,
            )
        }
    )
    view = present_encounter(session, JP_MUMU_ENCOUNTER_MAP_CATALOG, locale_id="en")

    assert view.items[0].value == expected
