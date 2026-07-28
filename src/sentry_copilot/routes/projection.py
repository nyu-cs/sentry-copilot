from __future__ import annotations

from typing import cast

import cv2
import numpy as np
import numpy.typing as npt

from .models import MapCalibration, PixelPoint, Point


class RouteProjector:
    """Project normalized battlefield coordinates to captured-frame pixels."""

    def homography(self, calibration: MapCalibration) -> npt.NDArray[np.float32]:
        normalized = np.array(
            [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]], dtype=np.float32
        )
        screen = np.array(
            [[point.x, point.y] for point in calibration.battlefield_corners], dtype=np.float32
        )
        return cast(npt.NDArray[np.float32], cv2.getPerspectiveTransform(normalized, screen))

    def project(self, point: Point, calibration: MapCalibration) -> PixelPoint:
        source = np.array([[[point.x, point.y]]], dtype=np.float32)
        result = cv2.perspectiveTransform(source, self.homography(calibration))[0][0]
        return PixelPoint(x=float(result[0]), y=float(result[1]))
