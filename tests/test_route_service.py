import numpy as np

from sentry_copilot.domain.enums import StageType
from sentry_copilot.routes.models import (
    ActorType,
    MapCalibration,
    PixelPoint,
    RouteQuery,
)
from sentry_copilot.routes.repository import MapRepository
from sentry_copilot.services.route_service import RouteOverlayService
from sentry_copilot.vision.interfaces import FixedCornerCalibrator, FixedMapRecognizer


def calibration(confidence: float = 1.0) -> MapCalibration:
    return MapCalibration(
        frame_width=1280,
        frame_height=720,
        battlefield_corners=[
            PixelPoint(x=100, y=90),
            PixelPoint(x=1180, y=90),
            PixelPoint(x=1180, y=650),
            PixelPoint(x=100, y=650),
        ],
        confidence=confidence,
    )


def query() -> RouteQuery:
    return RouteQuery(
        map_id="demo.synthetic_training_map",
        ruleset_id="demo.v1",
        actor_type=ActorType.ENEMY,
        stage_type=StageType.REGULAR,
        wave=7,
        actor_id="enemy.generic_placeholder",
    )


def test_low_map_confidence_suppresses_overlay() -> None:
    service = RouteOverlayService(
        repository=MapRepository.from_directory("data/maps"),
        recognizer=FixedMapRecognizer("demo.synthetic_training_map", confidence=0.2),
        calibrator=FixedCornerCalibrator(calibration()),
    )
    result = service.analyze(np.zeros((720, 1280, 3), dtype=np.uint8), query())
    assert result.rendered_frame is None
    assert result.routes == []
    assert result.reason == "map_unknown_or_low_confidence"


def test_confident_manual_context_renders_overlay() -> None:
    service = RouteOverlayService(
        repository=MapRepository.from_directory("data/maps"),
        recognizer=FixedMapRecognizer("demo.synthetic_training_map"),
        calibrator=FixedCornerCalibrator(calibration()),
    )
    result = service.analyze(np.zeros((720, 1280, 3), dtype=np.uint8), query())
    assert len(result.routes) == 1
    assert result.rendered_frame is not None
    assert int(result.rendered_frame.sum()) > 0
