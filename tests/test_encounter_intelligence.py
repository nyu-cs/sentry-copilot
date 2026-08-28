from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import numpy as np

from sentry_copilot.capture.frame_source import Frame, FrameSourceType
from sentry_copilot.encounter.catalog import JP_MUMU_ENCOUNTER_MAP_CATALOG, EncounterMapCatalog
from sentry_copilot.encounter.lifecycle import begin_encounter
from sentry_copilot.encounter.models import (
    CapturedDifficulty,
    CapturedMap,
    DifficultyDefinition,
    EncounterMapDefinition,
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
    )
    assert captured.session.ordinary_progress_count == 0
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
    assert view.items[0].complete is False
    assert view.items[0].value == "尚未识别"
    assert view.progress_label == "0 / 4"
    assert view.difficulty_value == "死地"

    with_map = difficulty_only.model_copy(
        update={"captured_map": CapturedMap(map_id="map.synthetic.battlefield", map_code="BF-1")}
    )
    map_view = present_encounter(with_map, catalog, locale_id="zh_CN")
    assert map_view.items[0].value == "BF-1 · 合成地图"
    assert map_view.progress_label == "1 / 4"


def test_jp_catalog_does_not_define_ac_3_as_a_battlefield() -> None:
    assert JP_MUMU_ENCOUNTER_MAP_CATALOG.by_code("AC-3") is None
    definition = JP_MUMU_ENCOUNTER_MAP_CATALOG.difficulty_by_simulation_code("AC-3")
    assert definition is not None
    assert definition.difficulty_id == "difficulty.covenant_latter.deadland"
