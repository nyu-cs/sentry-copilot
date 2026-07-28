from __future__ import annotations

from typing import Protocol

import numpy as np
import numpy.typing as npt
from pydantic import BaseModel, Field

from sentry_copilot.routes.models import MapCalibration, MapDefinition


class MapObservation(BaseModel):
    map_id: str | None
    confidence: float = Field(ge=0.0, le=1.0)
    source: str


class MapRecognizer(Protocol):
    def recognize(self, frame: npt.NDArray[np.uint8]) -> MapObservation: ...


class MapCalibrator(Protocol):
    def calibrate(
        self,
        frame: npt.NDArray[np.uint8],
        map_definition: MapDefinition,
    ) -> MapCalibration: ...


class FixedMapRecognizer:
    """Manual development provider used before real map recognition is implemented."""

    def __init__(self, map_id: str, confidence: float = 1.0) -> None:
        self.map_id = map_id
        self.confidence = confidence

    def recognize(self, frame: npt.NDArray[np.uint8]) -> MapObservation:
        del frame
        return MapObservation(map_id=self.map_id, confidence=self.confidence, source="manual")


class FixedCornerCalibrator:
    """Manual development provider backed by explicit battlefield corners."""

    def __init__(self, calibration: MapCalibration) -> None:
        self.calibration = calibration

    def calibrate(
        self,
        frame: npt.NDArray[np.uint8],
        map_definition: MapDefinition,
    ) -> MapCalibration:
        del frame, map_definition
        return self.calibration
