"""Read-only MuMu native-renderer IPC capture through the shared frame contract."""

from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from time import monotonic
from typing import Any, Protocol

import cv2
import numpy as np

from sentry_copilot.capture.frame_source import (
    Frame,
    FrameSource,
    FrameSourceMetadata,
    FrameSourceType,
    ImageArray,
)


class MuMuIpcCaptureError(RuntimeError):
    """A sanitized failure from MuMu's read-only renderer IPC capture API."""


class MuMuIpcBackend(Protocol):
    """Small screenshot-only boundary around the native renderer IPC ABI."""

    def connect(self, install_root: Path, instance_id: int) -> int: ...

    def disconnect(self, connection_id: int) -> None: ...

    def display_dimensions(self, connection_id: int, display_id: int) -> tuple[int, int]: ...

    def capture_rgba(
        self,
        connection_id: int,
        display_id: int,
        width: int,
        height: int,
        buffer: Any,
    ) -> None: ...


MuMuIpcBackendFactory = Callable[[Path], MuMuIpcBackend]
Clock = Callable[[], float]
UtcNow = Callable[[], datetime]


@dataclass
class MuMuIpcFrameSource(FrameSource):
    """Capture one explicit MuMu display using its installed native renderer IPC DLL.

    The validated target ABI supplies an upside-down RGBA framebuffer.  This source intentionally
    converts it into the repository-wide immutable BGR ``Frame`` payload before yielding it.
    It never invokes input, touch, or window-control APIs.
    """

    install_root: Path
    dll_path: Path
    instance_id: int = 0
    display_id: int = 0
    target_fps: float = 5.0
    source_id: str | None = None
    backend_factory: MuMuIpcBackendFactory = field(
        default_factory=lambda: _load_ctypes_backend,
        repr=False,
    )
    clock: Clock = field(default=monotonic, repr=False)
    utc_now: UtcNow = field(default=lambda: datetime.now(UTC), repr=False)
    _stop_requested: Event = field(default_factory=Event, init=False, repr=False)

    def __post_init__(self) -> None:
        self.install_root = Path(self.install_root)
        self.dll_path = Path(self.dll_path)
        if (
            not str(self.install_root).strip()
            or not str(self.dll_path).strip()
            or self.install_root == Path(".")
            or self.dll_path == Path(".")
        ):
            raise ValueError("MuMu install root and IPC DLL path must not be blank")
        if self.instance_id < 0 or self.display_id < 0:
            raise ValueError("MuMu instance_id and display_id must be non-negative")
        if self.target_fps <= 0:
            raise ValueError("target_fps must be positive")
        if self.source_id is None:
            self.source_id = f"mumu-ipc:instance-{self.instance_id}:display-{self.display_id}"
        elif not self.source_id.strip():
            raise ValueError("source_id must not be blank")

    @property
    def metadata(self) -> FrameSourceMetadata:
        return FrameSourceMetadata(
            source_id=self._source_id,
            source_type=FrameSourceType.MUMU_IPC,
            source_reference=(
                f"mumu-renderer-ipc:instance={self.instance_id},display={self.display_id}"
            ),
            frame_rate=self.target_fps,
        )

    @property
    def _source_id(self) -> str:
        assert self.source_id is not None
        return self.source_id

    def stop(self) -> None:
        """Request clean iterator completion and native connection release."""

        self._stop_requested.set()

    def frames(self) -> Iterator[Frame]:
        """Connect once, capture at bounded cadence, then disconnect exactly once."""

        if self._stop_requested.is_set():
            return
        backend: MuMuIpcBackend | None = None
        connection_id: int | None = None
        try:
            backend = self.backend_factory(self.dll_path)
            connection_id = backend.connect(self.install_root, self.instance_id)
            if connection_id <= 0:
                raise MuMuIpcCaptureError("MuMu renderer IPC connection was unavailable")
            width, height = backend.display_dimensions(connection_id, self.display_id)
            _validate_dimensions(width, height)
            buffer = (ctypes.c_ubyte * (width * height * 4))()
            started_at = self.clock()
            next_capture_at = started_at
            frame_index = 0
            while not self._stop_requested.is_set():
                backend.capture_rgba(connection_id, self.display_id, width, height, buffer)
                image = _owned_bgr_from_rgba_buffer(buffer, width, height)
                captured_at = self.utc_now()
                if captured_at.tzinfo is None or captured_at.utcoffset() is None:
                    raise MuMuIpcCaptureError("MuMu IPC capture clock returned a naive timestamp")
                yield Frame(
                    frame_id=f"{self._source_id}:{frame_index:06d}",
                    frame_index=frame_index,
                    processed_at=captured_at,
                    source_timestamp=timedelta(seconds=max(0.0, self.clock() - started_at)),
                    source_type=FrameSourceType.MUMU_IPC,
                    source_id=self._source_id,
                    width=width,
                    height=height,
                    image=image,
                    source_reference=self.metadata.source_reference,
                )
                frame_index += 1
                next_capture_at += 1 / self.target_fps
                wait_seconds = next_capture_at - self.clock()
                if wait_seconds > 0:
                    self._stop_requested.wait(wait_seconds)
                else:
                    next_capture_at = self.clock()
        except MuMuIpcCaptureError:
            raise
        except Exception as error:
            raise MuMuIpcCaptureError("MuMu renderer IPC capture failed") from error
        finally:
            if backend is not None and connection_id is not None and connection_id > 0:
                try:
                    backend.disconnect(connection_id)
                except Exception as error:
                    if not self._stop_requested.is_set():
                        raise MuMuIpcCaptureError("MuMu renderer IPC disconnect failed") from error


class _CtypesMuMuIpcBackend:
    """Exact ctypes binding for the target build's screenshot-only renderer ABI."""

    def __init__(self, library: object) -> None:
        self._connect = _required_function(library, "nemu_connect")
        self._disconnect = _required_function(library, "nemu_disconnect")
        self._capture = _required_function(library, "nemu_capture_display")
        self._connect.argtypes = [ctypes.c_wchar_p, ctypes.c_int]
        self._connect.restype = ctypes.c_int
        self._disconnect.argtypes = [ctypes.c_int]
        self._disconnect.restype = None
        self._capture.argtypes = [
            ctypes.c_int,
            ctypes.c_uint,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_ubyte),
        ]
        self._capture.restype = ctypes.c_int

    def connect(self, install_root: Path, instance_id: int) -> int:
        return int(self._connect(str(install_root), instance_id))

    def disconnect(self, connection_id: int) -> None:
        self._disconnect(connection_id)

    def display_dimensions(self, connection_id: int, display_id: int) -> tuple[int, int]:
        width = ctypes.c_int()
        height = ctypes.c_int()
        result = self._capture(
            connection_id,
            display_id,
            0,
            ctypes.byref(width),
            ctypes.byref(height),
            None,
        )
        if result != 0:
            raise MuMuIpcCaptureError("MuMu renderer IPC display query failed")
        return width.value, height.value

    def capture_rgba(
        self,
        connection_id: int,
        display_id: int,
        width: int,
        height: int,
        buffer: Any,
    ) -> None:
        result_width = ctypes.c_int(width)
        result_height = ctypes.c_int(height)
        result = self._capture(
            connection_id,
            display_id,
            len(buffer),
            ctypes.byref(result_width),
            ctypes.byref(result_height),
            buffer,
        )
        if result != 0:
            raise MuMuIpcCaptureError("MuMu renderer IPC display capture failed")
        if (result_width.value, result_height.value) != (width, height):
            raise MuMuIpcCaptureError("MuMu renderer IPC display dimensions changed unexpectedly")


def _load_ctypes_backend(dll_path: Path) -> MuMuIpcBackend:
    if sys.platform != "win32":
        raise MuMuIpcCaptureError("MuMu renderer IPC capture requires Windows")
    loader = getattr(ctypes, "WinDLL", None)
    if loader is None:
        raise MuMuIpcCaptureError("MuMu renderer IPC loader is unavailable")
    try:
        library = loader(str(dll_path))
    except OSError as error:
        raise MuMuIpcCaptureError("MuMu renderer IPC DLL is unavailable") from error
    return _CtypesMuMuIpcBackend(library)


def _required_function(library: object, name: str) -> Any:
    try:
        return getattr(library, name)
    except AttributeError as error:
        raise MuMuIpcCaptureError(
            "MuMu renderer IPC is missing required capture support"
        ) from error


def _validate_dimensions(width: int, height: int) -> None:
    if width <= 0 or height <= 0:
        raise MuMuIpcCaptureError("MuMu renderer IPC reported invalid display dimensions")


def _owned_bgr_from_rgba_buffer(buffer: Any, width: int, height: int) -> ImageArray:
    rgba = np.ctypeslib.as_array(buffer)
    if rgba.dtype != np.uint8 or rgba.size != width * height * 4:
        raise MuMuIpcCaptureError("MuMu renderer IPC returned an invalid framebuffer")
    rgba_image = rgba.reshape((height, width, 4))
    bgr = cv2.cvtColor(rgba_image, cv2.COLOR_RGBA2BGR)
    image = np.ascontiguousarray(np.flipud(bgr), dtype=np.uint8)
    if image.shape != (height, width, 3) or image.dtype != np.uint8:
        raise MuMuIpcCaptureError("MuMu renderer IPC produced an invalid BGR framebuffer")
    return image
