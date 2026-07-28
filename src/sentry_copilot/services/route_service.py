from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from sentry_copilot.routes.models import MapCalibration, RouteDefinition, RouteQuery
from sentry_copilot.routes.overlay import RouteOverlayRenderer
from sentry_copilot.routes.repository import MapRepository
from sentry_copilot.routes.selector import RouteSelector
from sentry_copilot.vision.interfaces import MapCalibrator, MapObservation, MapRecognizer


@dataclass(frozen=True)
class RouteAnalysisResult:
    map_observation: MapObservation
    calibration: MapCalibration | None
    routes: list[RouteDefinition]
    rendered_frame: npt.NDArray[np.uint8] | None
    reason: str | None = None


class RouteOverlayService:
    def __init__(
        self,
        repository: MapRepository,
        recognizer: MapRecognizer,
        calibrator: MapCalibrator,
        selector: RouteSelector | None = None,
        renderer: RouteOverlayRenderer | None = None,
        minimum_map_confidence: float = 0.8,
        minimum_calibration_confidence: float = 0.8,
    ) -> None:
        self.repository = repository
        self.recognizer = recognizer
        self.calibrator = calibrator
        self.selector = selector or RouteSelector()
        self.renderer = renderer or RouteOverlayRenderer()
        self.minimum_map_confidence = minimum_map_confidence
        self.minimum_calibration_confidence = minimum_calibration_confidence

    def analyze(
        self,
        frame: npt.NDArray[np.uint8],
        query: RouteQuery,
    ) -> RouteAnalysisResult:
        observation = self.recognizer.recognize(frame)
        if observation.map_id is None or observation.confidence < self.minimum_map_confidence:
            return RouteAnalysisResult(observation, None, [], None, "map_unknown_or_low_confidence")
        if observation.map_id != query.map_id:
            return RouteAnalysisResult(observation, None, [], None, "map_query_mismatch")

        map_definition = self.repository.get(observation.map_id)
        calibration = self.calibrator.calibrate(frame, map_definition)
        if calibration.confidence < self.minimum_calibration_confidence:
            return RouteAnalysisResult(
                observation,
                calibration,
                [],
                None,
                "calibration_low_confidence",
            )

        routes = self.selector.select(map_definition, query)
        rendered = self.renderer.render(frame, routes, calibration)
        return RouteAnalysisResult(observation, calibration, routes, rendered)
