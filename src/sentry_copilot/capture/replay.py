"""Compatibility imports for the unified offline frame-source contract."""

from .frame_source import Frame as FramePacket
from .frame_source import LocalVideoFrameSource as VideoFrameSource

__all__ = ["FramePacket", "VideoFrameSource"]
