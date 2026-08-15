from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from sentry_copilot.capture.display_smoke import (
    DisplayCaptureSmokeConfig,
    run_display_capture_smoke_test,
)
from sentry_copilot.capture.frame_source import (
    Frame,
    FrameSource,
    FrameSourceMetadata,
    FrameSourceType,
)
from sentry_copilot.capture.windows_display import (
    WindowsDisplayCaptureError,
    WindowsDisplayFrameSource,
)


class _Clock:
    def __init__(self) -> None:
        self.value = 10.0

    def now(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


class _Backend:
    def __init__(self, images: Sequence[np.ndarray]) -> None:
        self.monitors: Sequence[Mapping[str, int]] = (
            {"left": 0, "top": 0, "width": 30, "height": 20},
            {"left": 0, "top": 0, "width": 6, "height": 4},
        )
        self._images = iter(images)
        self.closed = False

    def grab(self, monitor: Mapping[str, int]) -> object:
        del monitor
        return next(self._images)

    def close(self) -> None:
        self.closed = True


class _StaticFrameSource(FrameSource):
    def __init__(self, frames: tuple[Frame, ...]) -> None:
        self._frames = frames

    @property
    def metadata(self) -> FrameSourceMetadata:
        return FrameSourceMetadata(
            source_id="synthetic-live",
            source_type=FrameSourceType.WINDOWS_DISPLAY,
            source_reference="synthetic-display",
            frame_rate=5.0,
        )

    def frames(self) -> Iterator[Frame]:
        return iter(self._frames)


def _frame(index: int) -> Frame:
    return Frame(
        frame_id=f"synthetic-live:{index:06d}",
        frame_index=index,
        processed_at=datetime(2026, 8, 15, tzinfo=UTC),
        source_timestamp=timedelta(seconds=index / 5),
        source_type=FrameSourceType.WINDOWS_DISPLAY,
        source_id="synthetic-live",
        width=6,
        height=4,
        image=np.full((4, 6, 3), index, dtype=np.uint8),
        source_reference="synthetic-display",
    )


def test_windows_display_source_emits_shared_immutable_frames_and_stops_cleanly() -> None:
    backend = _Backend(
        (
            np.full((4, 6, 4), 17, dtype=np.uint8),
            np.full((4, 6, 4), 18, dtype=np.uint8),
        )
    )
    clock = _Clock()
    source = WindowsDisplayFrameSource(
        monitor_index=1,
        target_fps=5.0,
        backend_factory=lambda: backend,
        clock=clock.now,
        sleeper=clock.sleep,
        utc_now=lambda: datetime(2026, 8, 15, tzinfo=UTC),
    )
    frames = source.frames()

    frame = next(frames)
    second = next(frames)
    source.stop()
    assert tuple(frames) == ()

    assert frame.frame_id == "windows-display:monitor-1:000000"
    assert frame.source_type == FrameSourceType.WINDOWS_DISPLAY
    assert (frame.width, frame.height) == (6, 4)
    assert frame.processed_at.tzinfo is not None
    assert frame.timestamp_seconds == 0.0
    assert second.timestamp_seconds == pytest.approx(0.2)
    assert source.metadata.frame_rate == 5.0
    assert not frame.image.flags.writeable
    assert np.array_equal(frame.image, np.full((4, 6, 3), 17, dtype=np.uint8))
    assert backend.closed


def test_windows_display_source_raises_typed_error_for_unavailable_monitor() -> None:
    backend = _Backend(())
    source = WindowsDisplayFrameSource(monitor_index=2, backend_factory=lambda: backend)

    with pytest.raises(WindowsDisplayCaptureError, match="unavailable"):
        next(source.frames())

    assert backend.closed


def test_windows_display_source_rejects_virtual_monitor_zero() -> None:
    with pytest.raises(ValueError, match="physical monitor"):
        WindowsDisplayFrameSource(monitor_index=0)


def test_windows_display_source_wraps_backend_grab_failure() -> None:
    backend = _Backend(())
    source = WindowsDisplayFrameSource(monitor_index=1, backend_factory=lambda: backend)

    with pytest.raises(WindowsDisplayCaptureError, match="failed to capture"):
        next(source.frames())

    assert backend.closed


def test_smoke_runner_writes_bounded_manifest_and_sampled_pngs(tmp_path: Path) -> None:
    frames = (_frame(0), _frame(1), _frame(2))
    original = np.array(frames[0].image, copy=True)
    source = _StaticFrameSource(frames)

    result = run_display_capture_smoke_test(
        source,
        DisplayCaptureSmokeConfig(
            output_directory=tmp_path / "smoke",
            frame_limit=2,
            dump_every_n=2,
        ),
    )

    records = [json.loads(line) for line in result.manifest_path.read_text().splitlines()]
    assert result.captured_frame_count == 2
    assert result.dumped_frame_count == 1
    assert [record["frame_index"] for record in records] == [0, 1]
    assert Path(records[0]["output_path"]).is_file()
    assert records[1]["output_path"] is None
    assert np.array_equal(frames[0].image, original)


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"duration_seconds": 1.0, "frame_limit": 1},
        {"duration_seconds": 0.0},
        {"frame_limit": 0},
    ],
)
def test_smoke_config_requires_one_positive_limit(kwargs: dict[str, float | int]) -> None:
    with pytest.raises(ValueError):
        DisplayCaptureSmokeConfig(output_directory=Path("synthetic"), **kwargs)
