from __future__ import annotations

import ctypes
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from sentry_copilot.capture.frame_source import FrameSourceType
from sentry_copilot.capture.mumu_ipc import (
    MuMuIpcCaptureError,
    MuMuIpcFrameSource,
    _CtypesMuMuIpcBackend,
)


class _Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def now(self) -> float:
        self.value += 0.1
        return self.value


class _Backend:
    def __init__(
        self,
        *,
        dimensions: tuple[int, int] = (2, 2),
        connection_id: int = 17,
        fail_capture: bool = False,
    ) -> None:
        self.dimensions = dimensions
        self.connection_id = connection_id
        self.fail_capture = fail_capture
        self.connect_calls = 0
        self.dimension_calls = 0
        self.capture_calls = 0
        self.disconnect_calls: list[int] = []

    def connect(self, install_root: Path, instance_id: int) -> int:
        del install_root, instance_id
        self.connect_calls += 1
        return self.connection_id

    def disconnect(self, connection_id: int) -> None:
        self.disconnect_calls.append(connection_id)

    def display_dimensions(self, connection_id: int, display_id: int) -> tuple[int, int]:
        assert connection_id == self.connection_id
        assert display_id == 0
        self.dimension_calls += 1
        return self.dimensions

    def capture_rgba(
        self,
        connection_id: int,
        display_id: int,
        width: int,
        height: int,
        buffer: object,
    ) -> None:
        assert connection_id == self.connection_id
        assert display_id == 0
        assert (width, height) == self.dimensions
        self.capture_calls += 1
        if self.fail_capture:
            raise MuMuIpcCaptureError("MuMu renderer IPC display capture failed")
        # Native rows are upside down.  RGBA values make the BGR conversion observable.
        raw = np.ctypeslib.as_array(buffer)  # type: ignore[arg-type]
        raw[:] = np.array(
            [
                255,
                0,
                0,
                255,  # native top: red
                0,
                255,
                0,
                255,  # native top: green
                0,
                0,
                255,
                255,  # native bottom: blue
                255,
                255,
                255,
                255,  # native bottom: white
            ],
            dtype=np.uint8,
        )


def _source(backend: _Backend, clock: _Clock | None = None) -> MuMuIpcFrameSource:
    ticker = clock or _Clock()
    return MuMuIpcFrameSource(
        install_root=Path("C:/MuMu"),
        dll_path=Path("C:/MuMu/external_renderer_ipc.dll"),
        target_fps=5.0,
        backend_factory=lambda _path: backend,
        clock=ticker.now,
        utc_now=lambda: datetime(2026, 8, 29, tzinfo=UTC),
    )


def test_mumu_ipc_source_reuses_one_connection_and_converts_owned_rgba_frames() -> None:
    backend = _Backend()
    source = _source(backend)
    frames = source.frames()

    first = next(frames)
    second = next(frames)
    source.stop()
    assert tuple(frames) == ()

    assert backend.connect_calls == 1
    assert backend.dimension_calls == 1
    assert backend.capture_calls == 2
    assert backend.disconnect_calls == [17]
    assert source.metadata.source_type is FrameSourceType.MUMU_IPC
    assert source.metadata.source_reference == "mumu-renderer-ipc:instance=0,display=0"
    assert first.frame_id == "mumu-ipc:instance-0:display-0:000000"
    assert second.frame_id == "mumu-ipc:instance-0:display-0:000001"
    assert first.processed_at.tzinfo is not None
    assert first.timestamp_seconds is not None and first.timestamp_seconds >= 0
    assert first.image.dtype == np.uint8
    assert first.image.shape == (2, 2, 3)
    assert not first.image.flags.writeable
    # BGR output after RGBA conversion and a vertical native-framebuffer flip.
    assert np.array_equal(
        first.image,
        np.array(
            [
                [[255, 0, 0], [255, 255, 255]],
                [[0, 0, 255], [0, 255, 0]],
            ],
            dtype=np.uint8,
        ),
    )


def test_mumu_ipc_source_does_not_restart_after_stop() -> None:
    backend = _Backend()
    source = _source(backend)

    source.stop()

    assert tuple(source.frames()) == ()
    assert backend.connect_calls == 0


@pytest.mark.parametrize(
    "kwargs",
    (
        {"install_root": Path(""), "dll_path": Path("dll")},
        {"install_root": Path("root"), "dll_path": Path("" )},
        {"install_root": Path("root"), "dll_path": Path("dll"), "instance_id": -1},
        {"install_root": Path("root"), "dll_path": Path("dll"), "display_id": -1},
        {"install_root": Path("root"), "dll_path": Path("dll"), "target_fps": 0.0},
    ),
)
def test_mumu_ipc_configuration_rejects_invalid_values(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        MuMuIpcFrameSource(**kwargs)  # type: ignore[arg-type]


def test_mumu_ipc_source_normalizes_dll_load_and_connect_failures() -> None:
    unavailable = MuMuIpcFrameSource(
        install_root=Path("root"),
        dll_path=Path("private.dll"),
        backend_factory=lambda _path: (_ for _ in ()).throw(
            MuMuIpcCaptureError("MuMu renderer IPC DLL is unavailable")
        ),
    )
    with pytest.raises(MuMuIpcCaptureError, match="DLL is unavailable"):
        next(unavailable.frames())

    backend = _Backend(connection_id=0)
    with pytest.raises(MuMuIpcCaptureError, match="connection was unavailable"):
        next(_source(backend).frames())
    assert backend.disconnect_calls == []


def test_mumu_ipc_source_handles_invalid_dimensions_and_capture_failure_then_disconnects() -> None:
    invalid = _Backend(dimensions=(0, 2))
    with pytest.raises(MuMuIpcCaptureError, match="invalid display dimensions"):
        next(_source(invalid).frames())
    assert invalid.disconnect_calls == [17]

    failing = _Backend(fail_capture=True)
    with pytest.raises(MuMuIpcCaptureError, match="display capture failed"):
        next(_source(failing).frames())
    assert failing.disconnect_calls == [17]


def test_ctypes_backend_rejects_missing_required_capture_symbol() -> None:
    class _MissingLibrary:
        nemu_connect = object()
        nemu_disconnect = object()

    with pytest.raises(MuMuIpcCaptureError, match="missing required capture support"):
        _CtypesMuMuIpcBackend(_MissingLibrary())


def test_ctypes_backend_uses_zero_length_dimension_query_and_checks_capture_dimensions() -> None:
    class _Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback
            self.argtypes: object | None = None
            self.restype: object | None = None

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    class _Library:
        def __init__(self) -> None:
            self.nemu_connect = _Function(lambda _root, _instance: 7)
            self.nemu_disconnect = _Function(lambda _connection: None)
            self.calls: list[tuple[int, int]] = []

            def capture(
                _connection: int,
                _display: int,
                length: int,
                width: object,
                height: object,
                _buffer: object,
            ) -> int:
                self.calls.append((length, 0 if _buffer is None else 1))
                ctypes.cast(width, ctypes.POINTER(ctypes.c_int))[0] = 2
                ctypes.cast(height, ctypes.POINTER(ctypes.c_int))[0] = 3
                return 0

            self.nemu_capture_display = _Function(capture)

    library = _Library()
    backend = _CtypesMuMuIpcBackend(library)
    assert backend.display_dimensions(7, 0) == (2, 3)
    buffer = (ctypes.c_ubyte * 24)()
    backend.capture_rgba(7, 0, 2, 3, buffer)
    assert library.calls == [(0, 0), (24, 1)]


def test_ctypes_backend_rejects_a_dimension_change_during_capture() -> None:
    class _Function:
        def __init__(self, callback: object) -> None:
            self.callback = callback
            self.argtypes: object | None = None
            self.restype: object | None = None

        def __call__(self, *args: object) -> object:
            return self.callback(*args)  # type: ignore[operator]

    class _Library:
        def __init__(self) -> None:
            self.nemu_connect = _Function(lambda _root, _instance: 7)
            self.nemu_disconnect = _Function(lambda _connection: None)

            def capture(
                _connection: int,
                _display: int,
                _length: int,
                width: object,
                height: object,
                _buffer: object,
            ) -> int:
                ctypes.cast(width, ctypes.POINTER(ctypes.c_int))[0] = 3
                ctypes.cast(height, ctypes.POINTER(ctypes.c_int))[0] = 2
                return 0

            self.nemu_capture_display = _Function(capture)

    backend = _CtypesMuMuIpcBackend(_Library())
    with pytest.raises(MuMuIpcCaptureError, match="dimensions changed unexpectedly"):
        backend.capture_rgba(7, 0, 2, 2, (ctypes.c_ubyte * 16)())
