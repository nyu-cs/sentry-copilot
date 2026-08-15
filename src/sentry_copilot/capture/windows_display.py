"""Read-only Windows physical-display capture using the shared frame-source contract."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import Event
from time import monotonic, sleep
from typing import Protocol, cast

import numpy as np

from sentry_copilot.capture.frame_source import (
    Frame,
    FrameSource,
    FrameSourceMetadata,
    FrameSourceType,
    ImageArray,
)


class WindowsDisplayCaptureError(RuntimeError):
    """A typed failure while opening or reading a physical Windows display."""


class DisplayCaptureBackend(Protocol):
    """The small subset of an MSS capture object required by this source."""

    @property
    def monitors(self) -> Sequence[Mapping[str, int]]: ...

    def grab(self, monitor: Mapping[str, int]) -> object: ...

    def close(self) -> None: ...


DisplayCaptureBackendFactory = Callable[[], DisplayCaptureBackend]
Clock = Callable[[], float]
Sleeper = Callable[[float], None]
UtcNow = Callable[[], datetime]


@dataclass
class WindowsDisplayFrameSource(FrameSource):
    """Capture one explicitly selected physical monitor as immutable BGR frames.

    MSS monitor index zero is the aggregate virtual display and is intentionally rejected: callers
    must select a real monitor starting from one. MSS returns physical monitor pixels on Windows;
    dimensions are read from each captured image rather than inferred from DPI-scaled coordinates.
    """

    monitor_index: int = 1
    target_fps: float = 5.0
    source_id: str | None = None
    backend_factory: DisplayCaptureBackendFactory = field(default_factory=lambda: _mss_backend)
    clock: Clock = field(default=monotonic, repr=False)
    sleeper: Sleeper = field(default=sleep, repr=False)
    utc_now: UtcNow = field(default=lambda: datetime.now(UTC), repr=False)
    _stop_requested: Event = field(default_factory=Event, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.monitor_index < 1:
            raise ValueError("monitor_index must select a physical monitor starting at 1")
        if self.target_fps <= 0:
            raise ValueError("target_fps must be positive")
        if self.source_id is None:
            self.source_id = f"windows-display:monitor-{self.monitor_index}"
        elif not self.source_id.strip():
            raise ValueError("source_id must not be blank")

    @property
    def metadata(self) -> FrameSourceMetadata:
        return FrameSourceMetadata(
            source_id=self._source_id,
            source_type=FrameSourceType.WINDOWS_DISPLAY,
            source_reference=f"physical-monitor:{self.monitor_index}",
            frame_rate=self.target_fps,
        )

    @property
    def _source_id(self) -> str:
        assert self.source_id is not None
        return self.source_id

    def stop(self) -> None:
        """Request that an active frame iterator finish and release its backend."""

        self._stop_requested.set()

    def frames(self) -> Iterator[Frame]:
        """Start capture and release MSS cleanly when stopped, exhausted, or closed."""

        self._stop_requested.clear()
        backend: DisplayCaptureBackend | None = None
        try:
            backend = self.backend_factory()
            monitor = _select_physical_monitor(backend.monitors, self.monitor_index)
            started_at = self.clock()
            next_capture_at = started_at
            frame_index = 0
            while not self._stop_requested.is_set():
                try:
                    screenshot = backend.grab(monitor)
                    image = _bgr_image(screenshot)
                except WindowsDisplayCaptureError:
                    raise
                except Exception as error:
                    raise WindowsDisplayCaptureError(
                        f"failed to capture physical monitor {self.monitor_index}"
                    ) from error
                captured_at = self.utc_now()
                if captured_at.tzinfo is None or captured_at.utcoffset() is None:
                    raise WindowsDisplayCaptureError("capture clock returned a naive timestamp")
                height, width = image.shape[:2]
                yield Frame(
                    frame_id=f"{self._source_id}:{frame_index:06d}",
                    frame_index=frame_index,
                    processed_at=captured_at,
                    source_timestamp=timedelta(seconds=max(0.0, self.clock() - started_at)),
                    source_type=FrameSourceType.WINDOWS_DISPLAY,
                    source_id=self._source_id,
                    width=width,
                    height=height,
                    image=image,
                    source_reference=_monitor_reference(self.monitor_index, monitor),
                )
                frame_index += 1
                next_capture_at += 1 / self.target_fps
                wait_seconds = next_capture_at - self.clock()
                if wait_seconds > 0:
                    self.sleeper(wait_seconds)
                else:
                    next_capture_at = self.clock()
        finally:
            if backend is not None:
                backend.close()


def _mss_backend() -> DisplayCaptureBackend:
    try:
        from mss import mss

        return cast(DisplayCaptureBackend, mss())
    except Exception as error:
        raise WindowsDisplayCaptureError("unable to start MSS Windows display capture") from error


def _select_physical_monitor(
    monitors: Sequence[Mapping[str, int]], monitor_index: int
) -> Mapping[str, int]:
    if monitor_index >= len(monitors):
        raise WindowsDisplayCaptureError(
            f"physical monitor {monitor_index} is unavailable; MSS reported {len(monitors) - 1}"
        )
    monitor = monitors[monitor_index]
    required = ("left", "top", "width", "height")
    if any(key not in monitor for key in required):
        raise WindowsDisplayCaptureError("MSS monitor metadata is incomplete")
    if monitor["width"] <= 0 or monitor["height"] <= 0:
        raise WindowsDisplayCaptureError("MSS monitor dimensions must be positive")
    return monitor


def _bgr_image(screenshot: object) -> ImageArray:
    payload = np.asarray(screenshot)
    if payload.dtype != np.uint8 or payload.ndim != 3 or payload.shape[2] != 4:
        raise WindowsDisplayCaptureError("MSS capture must be a uint8 BGRA image")
    return cast(ImageArray, np.array(payload[:, :, :3], dtype=np.uint8, copy=True))


def _monitor_reference(monitor_index: int, monitor: Mapping[str, int]) -> str:
    return (
        f"physical-monitor:{monitor_index}:"
        f"left={monitor['left']},top={monitor['top']},"
        f"width={monitor['width']},height={monitor['height']}"
    )
