from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest

from sentry_copilot.capture.frame_source import ImageSequenceFrameSource
from sentry_copilot.image_io import ImageDecodeError, load_bgr_image


def _image() -> np.ndarray[tuple[int, int, int], np.dtype[np.uint8]]:
    return np.array([[[1, 2, 3], [40, 50, 60]]], dtype=np.uint8)


def _write_png(path: Path, image: np.ndarray[tuple[int, int, int], np.dtype[np.uint8]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    path.write_bytes(encoded.tobytes())


def test_unicode_path_decodes_bgr_image_for_shared_loader_and_frame_source(tmp_path: Path) -> None:
    path = tmp_path / "卫戍协议" / "策略头像.png"
    expected = _image()
    _write_png(path, expected)

    decoded = load_bgr_image(path)
    frame = next(iter(ImageSequenceFrameSource((path,))))

    assert decoded.dtype == np.uint8
    assert decoded.shape == (1, 2, 3)
    assert np.array_equal(decoded, expected)
    assert np.array_equal(frame.image, expected)


def test_unicode_path_invalid_image_fails_cleanly(tmp_path: Path) -> None:
    path = tmp_path / "卫戍协议" / "损坏策略头像.png"
    path.parent.mkdir()
    path.write_bytes(b"not a PNG")

    with pytest.raises(ImageDecodeError, match="cannot decode image"):
        load_bgr_image(path)


def test_ascii_path_decoding_remains_supported(tmp_path: Path) -> None:
    path = tmp_path / "ascii" / "template.png"
    expected = _image()
    _write_png(path, expected)

    assert np.array_equal(load_bgr_image(path), expected)
