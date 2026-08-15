"""Bounded, caller-directed smoke captures for the Windows display source."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep

import cv2

from sentry_copilot.capture.frame_source import FrameSource
from sentry_copilot.capture.windows_display import WindowsDisplayFrameSource


@dataclass(frozen=True)
class DisplayCaptureSmokeConfig:
    """Explicit bounded capture settings for a manual local smoke test."""

    output_directory: Path
    duration_seconds: float | None = None
    frame_limit: int | None = None
    start_delay_seconds: float = 0.0
    dump_every_n: int | None = None

    def __post_init__(self) -> None:
        if (self.duration_seconds is None) == (self.frame_limit is None):
            raise ValueError("choose exactly one of duration_seconds or frame_limit")
        if self.duration_seconds is not None and self.duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        if self.frame_limit is not None and self.frame_limit <= 0:
            raise ValueError("frame_limit must be positive")
        if self.start_delay_seconds < 0:
            raise ValueError("start_delay_seconds must be non-negative")
        if self.dump_every_n is not None and self.dump_every_n <= 0:
            raise ValueError("dump_every_n must be positive when provided")


@dataclass(frozen=True)
class DisplayCaptureSmokeResult:
    output_directory: Path
    manifest_path: Path
    captured_frame_count: int
    dumped_frame_count: int


def run_display_capture_smoke_test(
    source: FrameSource,
    config: DisplayCaptureSmokeConfig,
    *,
    clock: Callable[[], float] = monotonic,
    sleeper: Callable[[float], None] = sleep,
) -> DisplayCaptureSmokeResult:
    """Capture a bounded caller-requested sample without modifying source frames or domain state."""

    if config.start_delay_seconds:
        sleeper(config.start_delay_seconds)
    config.output_directory.mkdir(parents=True, exist_ok=True)
    dump_directory = config.output_directory / "frames"
    if config.dump_every_n is not None:
        dump_directory.mkdir(parents=True, exist_ok=True)
    manifest_path = config.output_directory / "manifest.jsonl"
    captured = 0
    dumped = 0
    started_at = clock()
    frames = source.frames()

    try:
        with manifest_path.open("w", encoding="utf-8", newline="\n") as manifest:
            for frame in frames:
                if (
                    config.duration_seconds is not None
                    and clock() - started_at >= config.duration_seconds
                ):
                    break
                output_path: Path | None = None
                if config.dump_every_n is not None and captured % config.dump_every_n == 0:
                    output_path = dump_directory / f"frame_{frame.frame_index:06d}.png"
                    if not cv2.imwrite(str(output_path), frame.image):
                        raise OSError(f"cannot write display smoke frame: {output_path}")
                    dumped += 1
                manifest.write(
                    json.dumps(
                        {
                            "frame_id": frame.frame_id,
                            "frame_index": frame.frame_index,
                            "source_timestamp_seconds": frame.timestamp_seconds,
                            "width": frame.width,
                            "height": frame.height,
                            "output_path": str(output_path) if output_path is not None else None,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                    + "\n"
                )
                captured += 1
                if config.frame_limit is not None and captured >= config.frame_limit:
                    break
    finally:
        if isinstance(source, WindowsDisplayFrameSource):
            source.stop()
        close = getattr(frames, "close", None)
        if callable(close):
            close()

    return DisplayCaptureSmokeResult(
        output_directory=config.output_directory,
        manifest_path=manifest_path,
        captured_frame_count=captured,
        dumped_frame_count=dumped,
    )
