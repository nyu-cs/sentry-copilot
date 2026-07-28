from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import cv2
import numpy as np
import numpy.typing as npt


@dataclass(frozen=True)
class FramePacket:
    frame: npt.NDArray[np.uint8]
    timestamp_seconds: float
    frame_index: int


class VideoFrameSource:
    def __init__(self, path: str | Path, sample_every_seconds: float = 0.5) -> None:
        if sample_every_seconds <= 0:
            raise ValueError("sample_every_seconds must be positive")
        self.path = Path(path)
        self.sample_every_seconds = sample_every_seconds

    def frames(self) -> Iterator[FramePacket]:
        capture = cv2.VideoCapture(str(self.path))
        if not capture.isOpened():
            raise FileNotFoundError(f"cannot open video: {self.path}")
        fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        step = max(1, round(fps * self.sample_every_seconds))
        frame_index = 0
        try:
            while True:
                ok, frame = capture.read()
                if not ok:
                    break
                if frame_index % step == 0:
                    yield FramePacket(
                        cast(npt.NDArray[np.uint8], frame),
                        frame_index / fps,
                        frame_index,
                    )
                frame_index += 1
        finally:
            capture.release()
