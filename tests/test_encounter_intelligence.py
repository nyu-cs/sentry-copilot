from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import numpy as np

from sentry_copilot.capture.frame_source import Frame, FrameSourceType
from sentry_copilot.encounter.catalog import JP_MUMU_ENCOUNTER_MAP_CATALOG, EncounterMapCatalog
from sentry_copilot.encounter.lifecycle import begin_encounter
from sentry_copilot.encounter.models import (
    CapturedMap,
    DifficultyDefinition,
    EncounterCaptureItem,
    EncounterMapDefinition,
    LocalizedText,
    MapKnowledgeCategory,
    MapKnowledgeEntry,
)
from sentry_copilot.encounter.presentation import present_encounter
from sentry_copilot.encounter.session import MapCaptureUpdateStatus, apply_operation_map_observation
from sentry_copilot.vision.ocr import OcrBackend, OcrBackendReading
from sentry_copilot.vision.operation_map import (
    JP_MUMU_OPERATION_DIFFICULTY_ROI,
    JP_MUMU_OPERATION_MAP_CODE_ROI,
    OperationMapObservation,
    OperationMapState,
    observe_jp_mumu_operation_map,
)
from sentry_copilot.vision.viewport import ContentViewport, PixelRoi


class _OperationOcrBackend:
    async def recognize(self, image: np.ndarray, *, language_tag: str) -> OcrBackendReading:
        assert language_tag == "ja-JP"
        return OcrBackendReading("AC 3 」" if image.shape[1] == 480 else "死 地")


class _UnknownCodeBackend:
    async def recognize(self, image: np.ndarray, *, language_tag: str) -> OcrBackendReading:
        return OcrBackendReading("not a stage")


def _operation_frame() -> Frame:
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


def _observe(frame: Frame, backend: OcrBackend) -> OperationMapObservation:
    return asyncio.run(
        observe_jp_mumu_operation_map(frame, ContentViewport.full_frame(frame), backend)
    )


def test_operation_map_observer_normalizes_code_and_preserves_provenance() -> None:
    frame = _operation_frame()
    observation = _observe(frame, _OperationOcrBackend())

    assert observation.state is OperationMapState.OBSERVED
    assert observation.map_code == "AC-3"
    assert observation.difficulty_id == "difficulty.covenant_latter.deadland"
    assert observation.observed_difficulty == "死地"
    assert observation.map_code_ocr is not None
    assert observation.map_code_ocr.pixel_bounds == JP_MUMU_OPERATION_MAP_CODE_ROI
    assert observation.difficulty_ocr is not None
    assert observation.difficulty_ocr.pixel_bounds == JP_MUMU_OPERATION_DIFFICULTY_ROI
    assert observation.frame_id == frame.frame_id
    assert observation.processed_at == frame.processed_at
    assert observation.source_timestamp == frame.source_timestamp


def test_operation_map_observer_rejects_unknown_code_and_wrong_layout() -> None:
    frame = _operation_frame()
    unresolved = _observe(frame, _UnknownCodeBackend())
    assert unresolved.state is OperationMapState.UNRESOLVED

    wrong_viewport = ContentViewport(
        frame_id=frame.frame_id,
        frame_width=frame.width,
        frame_height=frame.height,
        pixel_roi=PixelRoi(x=1, y=0, width=1919, height=1080),
    )
    wrong_layout = asyncio.run(
        observe_jp_mumu_operation_map(frame, wrong_viewport, _OperationOcrBackend())
    )
    assert wrong_layout.state is OperationMapState.UNRESOLVED


def test_operation_map_observer_keeps_unvalidated_difficulty_unresolved() -> None:
    observation = _observe(_operation_frame(), _CodeAndDifficultyBackend("AC-3", "未校准"))

    assert observation.state is OperationMapState.OBSERVED
    assert observation.map_code == "AC-3"
    assert observation.difficulty_id is None
    assert observation.observed_difficulty is None
    assert observation.difficulty_ocr is not None
    assert observation.difficulty_ocr.normalized_text == "未校准"


def test_encounter_map_capture_progress_preservation_and_conflict() -> None:
    frame = _operation_frame()
    observed = _observe(frame, _OperationOcrBackend())
    fresh = begin_encounter("encounter.synthetic.1")
    captured = apply_operation_map_observation(fresh, observed, JP_MUMU_ENCOUNTER_MAP_CATALOG)
    assert captured.status is MapCaptureUpdateStatus.CAPTURED
    assert captured.session.ordinary_progress_count == 1
    assert captured.session.missing_items == (
        EncounterCaptureItem.BOSS,
        EncounterCaptureItem.ENEMY_TYPES,
        EncounterCaptureItem.BANNED_COVENANTS,
    )

    preserved = apply_operation_map_observation(
        captured.session,
        _observe(frame, _UnknownCodeBackend()),
        JP_MUMU_ENCOUNTER_MAP_CATALOG,
    )
    assert preserved.status is MapCaptureUpdateStatus.UNRESOLVED
    assert preserved.session.captured_map == captured.session.captured_map

    conflicting_catalog = EncounterMapCatalog(
        definitions=(
            *JP_MUMU_ENCOUNTER_MAP_CATALOG.definitions,
            EncounterMapDefinition(
                map_id="map.synthetic.ac_4",
                map_code="AC-4",
                names=(LocalizedText(locale_id="en", text="Synthetic"),),
            ),
        ),
        difficulties=JP_MUMU_ENCOUNTER_MAP_CATALOG.difficulties,
    )
    conflict_frame = _operation_frame()
    conflict = _observe(conflict_frame, _CodeBackend("AC-4"))
    result = apply_operation_map_observation(captured.session, conflict, conflicting_catalog)
    assert result.status is MapCaptureUpdateStatus.CONFLICT
    assert result.session.captured_map == captured.session.captured_map
    assert result.session.map_conflict is not None


def test_same_map_later_difficulty_enriches_without_changing_progress() -> None:
    frame = _operation_frame()
    unresolved_difficulty = _observe(frame, _CodeAndDifficultyBackend("AC-3", "未校准"))
    deadland = _observe(frame, _OperationOcrBackend())

    initial = apply_operation_map_observation(
        begin_encounter("encounter.synthetic.enrich"),
        unresolved_difficulty,
        JP_MUMU_ENCOUNTER_MAP_CATALOG,
    )
    assert initial.status is MapCaptureUpdateStatus.CAPTURED
    assert initial.session.captured_map is not None
    assert initial.session.captured_map.difficulty_id is None

    enriched = apply_operation_map_observation(
        initial.session,
        deadland,
        JP_MUMU_ENCOUNTER_MAP_CATALOG,
    )
    assert enriched.status is MapCaptureUpdateStatus.ENRICHED
    assert enriched.session.captured_map is not None
    assert enriched.session.captured_map.map_id == "map.covenant_latter.ac_3"
    assert enriched.session.captured_map.difficulty_id == "difficulty.covenant_latter.deadland"
    assert enriched.session.captured_map.observed_difficulty == "死地"
    assert enriched.session.ordinary_progress_count == 1

    weak_later = apply_operation_map_observation(
        enriched.session,
        unresolved_difficulty,
        JP_MUMU_ENCOUNTER_MAP_CATALOG,
    )
    repeated = apply_operation_map_observation(
        weak_later.session,
        deadland,
        JP_MUMU_ENCOUNTER_MAP_CATALOG,
    )
    assert weak_later.status is MapCaptureUpdateStatus.PRESERVED
    assert repeated.status is MapCaptureUpdateStatus.PRESERVED
    assert repeated.session.captured_map == enriched.session.captured_map


def test_same_map_different_validated_difficulties_preserve_a_conflict() -> None:
    catalog = EncounterMapCatalog(
        definitions=(
            EncounterMapDefinition(
                map_id="map.synthetic.ac_3",
                map_code="AC-3",
                allowed_difficulty_ids=(
                    "difficulty.synthetic.deadland",
                    "difficulty.synthetic.adversity",
                ),
            ),
        ),
        difficulties=(
            DifficultyDefinition(
                difficulty_id="difficulty.synthetic.deadland",
                names=(LocalizedText(locale_id="zh_CN", text="死地"),),
            ),
            DifficultyDefinition(
                difficulty_id="difficulty.synthetic.adversity",
                names=(LocalizedText(locale_id="zh_CN", text="逆境"),),
            ),
        ),
    )
    deadland = replace(
        _observe(_operation_frame(), _OperationOcrBackend()),
        difficulty_id="difficulty.synthetic.deadland",
    )
    adversity = replace(
        deadland,
        difficulty_id="difficulty.synthetic.adversity",
        observed_difficulty="逆境",
    )
    initial = apply_operation_map_observation(
        begin_encounter("encounter.synthetic.conflict"),
        deadland,
        catalog,
    )
    result = apply_operation_map_observation(initial.session, adversity, catalog)

    assert result.status is MapCaptureUpdateStatus.CONFLICT
    assert result.session.captured_map == initial.session.captured_map
    assert result.session.difficulty_conflict is not None
    assert (
        result.session.difficulty_conflict.existing_difficulty_id
        == "difficulty.synthetic.deadland"
    )
    assert (
        result.session.difficulty_conflict.conflicting_difficulty_id
        == "difficulty.synthetic.adversity"
    )


def test_presentation_localizes_progress_and_map_knowledge_with_fallback() -> None:
    catalog = EncounterMapCatalog(
        (
            EncounterMapDefinition(
                map_id="map.synthetic.ac_3",
                map_code="AC-3",
                names=(LocalizedText(locale_id="zh_CN", text="合成地图"),),
                knowledge_entries=(
                    MapKnowledgeEntry(
                        entry_id="fact.synthetic.terrain",
                        category=MapKnowledgeCategory.TERRAIN,
                        titles=(LocalizedText(locale_id="zh_CN", text="特殊地形"),),
                        descriptions=(LocalizedText(locale_id="zh_CN", text="仅用于测试"),),
                        source_note="synthetic",
                    ),
                    MapKnowledgeEntry(
                        entry_id="fact.synthetic.difficulty",
                        category=MapKnowledgeCategory.WARNING,
                        titles=(LocalizedText(locale_id="zh_CN", text="限定难度"),),
                        descriptions=(LocalizedText(locale_id="zh_CN", text="不应在未知难度显示"),),
                        source_note="synthetic",
                        difficulty_ids=("difficulty.synthetic.hard",),
                    ),
                ),
            ),
        ),
        difficulties=(
            DifficultyDefinition(
                difficulty_id="difficulty.synthetic.hard",
                names=(LocalizedText(locale_id="zh_CN", text="合成困难"),),
            ),
        ),
    )
    session = begin_encounter("encounter.synthetic.2").model_copy(
        update={"captured_map": CapturedMap(map_id="map.synthetic.ac_3", map_code="AC-3")}
    )

    chinese = present_encounter(session, catalog, locale_id="zh_CN")
    english = present_encounter(session, catalog, locale_id="en")
    assert chinese.title == "本局情报"
    assert chinese.progress_label == "1 / 4"
    assert chinese.items[0].complete is True
    assert chinese.items[0].value == "AC-3 · 合成地图"
    assert english.title == "Encounter Intel"
    assert english.items[0].value == "AC-3 · 合成地图"
    assert english.map_knowledge[0].title == "特殊地形"
    assert len(chinese.map_knowledge) == 1


def test_map_identity_and_difficulty_are_independent_in_presentation() -> None:
    catalog = EncounterMapCatalog(
        definitions=(
            EncounterMapDefinition(
                map_id="map.synthetic.ac_3",
                map_code="AC-3",
                allowed_difficulty_ids=(
                    "difficulty.synthetic.deadland",
                    "difficulty.synthetic.adversity",
                ),
            ),
        ),
        difficulties=(
            DifficultyDefinition(
                difficulty_id="difficulty.synthetic.deadland",
                names=(LocalizedText(locale_id="zh_CN", text="死地"),),
            ),
            DifficultyDefinition(
                difficulty_id="difficulty.synthetic.adversity",
                names=(LocalizedText(locale_id="zh_CN", text="逆境"),),
            ),
        ),
    )
    deadland_session = begin_encounter("encounter.synthetic.deadland").model_copy(
        update={
            "captured_map": CapturedMap(
                map_id="map.synthetic.ac_3",
                map_code="AC-3",
                difficulty_id="difficulty.synthetic.deadland",
                observed_difficulty="死地",
            )
        }
    )
    adversity_session = deadland_session.model_copy(
        update={
            "captured_map": CapturedMap(
                map_id="map.synthetic.ac_3",
                map_code="AC-3",
                difficulty_id="difficulty.synthetic.adversity",
                observed_difficulty="逆境",
            )
        }
    )

    deadland = present_encounter(deadland_session, catalog, locale_id="zh_CN")
    adversity = present_encounter(adversity_session, catalog, locale_id="zh_CN")
    assert deadland.items[0].value == "AC-3"
    assert adversity.items[0].value == "AC-3"
    assert deadland.difficulty_value == "死地"
    assert adversity.difficulty_value == "逆境"
    assert deadland.progress_label == "1 / 4"


def test_ac_3_visual_calibration_does_not_restrict_allowed_difficulties() -> None:
    definition = JP_MUMU_ENCOUNTER_MAP_CATALOG.by_code("AC-3")
    assert definition is not None
    assert definition.allowed_difficulty_ids == ()


class _CodeBackend:
    def __init__(self, code: str) -> None:
        self.code = code

    async def recognize(self, image: np.ndarray, *, language_tag: str) -> OcrBackendReading:
        return OcrBackendReading(self.code if image.shape[1] == 480 else "title")


class _CodeAndDifficultyBackend:
    def __init__(self, code: str, difficulty: str) -> None:
        self.code = code
        self.difficulty = difficulty

    async def recognize(self, image: np.ndarray, *, language_tag: str) -> OcrBackendReading:
        return OcrBackendReading(self.code if image.shape[1] == 480 else self.difficulty)
