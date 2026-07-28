from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
import numpy.typing as npt

from .models import (
    ActorType,
    MapCalibration,
    MoveStep,
    PhaseChangeStep,
    Point,
    RouteDefinition,
    TeleportStep,
    WaitStep,
)
from .projection import RouteProjector


@dataclass(frozen=True)
class OverlayStyle:
    enemy_bgr: tuple[int, int, int] = (255, 220, 0)
    boss_bgr: tuple[int, int, int] = (60, 60, 255)
    text_bgr: tuple[int, int, int] = (255, 255, 255)
    thickness: int = 4


class RouteOverlayRenderer:
    def __init__(
        self,
        projector: RouteProjector | None = None,
        style: OverlayStyle | None = None,
    ) -> None:
        self.projector = projector or RouteProjector()
        self.style = style or OverlayStyle()

    def render(
        self,
        frame: npt.NDArray[np.uint8],
        routes: list[RouteDefinition],
        calibration: MapCalibration,
    ) -> npt.NDArray[np.uint8]:
        output = frame.copy()
        for route in routes:
            color = (
                self.style.boss_bgr
                if route.actor_type == ActorType.BOSS
                else self.style.enemy_bgr
            )
            first_pixel: tuple[int, int] | None = None
            for step in route.steps:
                if isinstance(step, MoveStep):
                    points = [self._pixel(point, calibration) for point in step.points]
                    first_pixel = first_pixel or points[0]
                    self._draw_move(output, points, color)
                elif isinstance(step, TeleportStep):
                    start = self._pixel(step.from_point, calibration)
                    end = self._pixel(step.to_point, calibration)
                    first_pixel = first_pixel or start
                    self._draw_teleport(output, start, end, color)
                elif isinstance(step, WaitStep):
                    point = self._pixel(step.at, calibration)
                    first_pixel = first_pixel or point
                    cv2.circle(output, point, 9, color, -1)
                elif isinstance(step, PhaseChangeStep):
                    point = self._pixel(step.at, calibration)
                    first_pixel = first_pixel or point
                    cv2.drawMarker(
                        output,
                        point,
                        color,
                        markerType=cv2.MARKER_DIAMOND,
                        markerSize=22,
                        thickness=3,
                    )
            if first_pixel is not None:
                self._draw_label(output, route, first_pixel)
        return output

    def _pixel(self, point: Point, calibration: MapCalibration) -> tuple[int, int]:
        projected = self.projector.project(point, calibration)
        return round(projected.x), round(projected.y)

    def _draw_move(
        self,
        frame: npt.NDArray[np.uint8],
        points: list[tuple[int, int]],
        color: tuple[int, int, int],
    ) -> None:
        for start, end in zip(points, points[1:], strict=False):
            cv2.arrowedLine(
                frame,
                start,
                end,
                color,
                self.style.thickness,
                line_type=cv2.LINE_AA,
                tipLength=0.12,
            )

    def _draw_teleport(
        self,
        frame: npt.NDArray[np.uint8],
        start: tuple[int, int],
        end: tuple[int, int],
        color: tuple[int, int, int],
    ) -> None:
        for index in range(10):
            if index % 2:
                continue
            t0 = index / 10
            t1 = min((index + 1) / 10, 1.0)
            p0 = (
                round(start[0] + (end[0] - start[0]) * t0),
                round(start[1] + (end[1] - start[1]) * t0),
            )
            p1 = (
                round(start[0] + (end[0] - start[0]) * t1),
                round(start[1] + (end[1] - start[1]) * t1),
            )
            cv2.line(frame, p0, p1, color, self.style.thickness, lineType=cv2.LINE_AA)
        cv2.circle(frame, start, 9, color, 2)
        cv2.circle(frame, end, 9, color, 2)

    def _draw_label(
        self,
        frame: npt.NDArray[np.uint8],
        route: RouteDefinition,
        anchor: tuple[int, int],
    ) -> None:
        suffix = " [provisional]" if route.verification.value == "placeholder" else ""
        cv2.putText(
            frame,
            f"{route.label}{suffix}",
            (anchor[0], max(24, anchor[1] - 12)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            self.style.text_bgr,
            2,
            lineType=cv2.LINE_AA,
        )
