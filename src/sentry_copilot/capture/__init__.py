"""Offline frame inputs; capture produces frames and never domain observations."""

from .frame_source import (
    Frame,
    FrameSource,
    FrameSourceMetadata,
    FrameSourceType,
    ImageSequenceFrameSource,
    LocalVideoFrameSource,
    RawFrameDump,
    dump_raw_frames,
)
from .windows_display import WindowsDisplayCaptureError, WindowsDisplayFrameSource

__all__ = [
    "Frame",
    "FrameSource",
    "FrameSourceMetadata",
    "FrameSourceType",
    "ImageSequenceFrameSource",
    "LocalVideoFrameSource",
    "RawFrameDump",
    "dump_raw_frames",
    "WindowsDisplayCaptureError",
    "WindowsDisplayFrameSource",
]
