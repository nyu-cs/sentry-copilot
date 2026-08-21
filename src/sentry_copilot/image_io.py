"""Small Unicode-safe local BGR image I/O helpers.

OpenCV's path-based image readers and writers can fail on Unicode Windows paths.
These helpers operate on exactly one caller-supplied ``Path`` through Python's
Unicode-safe byte I/O while preserving the project-wide uint8 BGR contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import cv2
import numpy as np
import numpy.typing as npt

type BgrImage = npt.NDArray[np.uint8]


class ImageDecodeError(ValueError):
    """A caller-supplied local image could not be read or decoded."""


class ImageEncodeError(ValueError):
    """A caller-supplied PNG destination or BGR payload could not be encoded or written."""


def load_bgr_image(path: str | Path) -> BgrImage:
    """Decode exactly one image path as an unchanged three-channel BGR payload."""

    source = Path(path)
    try:
        encoded = source.read_bytes()
    except OSError as error:
        raise ImageDecodeError(f"cannot read image: {source}") from error

    image = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or not _is_bgr_image(image):
        raise ImageDecodeError(f"cannot decode image: {source}")
    return cast(BgrImage, image)


def write_bgr_png(path: str | Path, image: BgrImage) -> Path:
    """Encode one unchanged BGR image as PNG at an existing caller-owned destination."""

    destination = Path(path)
    if destination.suffix.lower() != ".png":
        raise ImageEncodeError(f"PNG destination must use a .png suffix: {destination}")
    if not _is_bgr_image(image):
        raise ImageEncodeError("image must be a uint8 BGR image")
    try:
        encoded_ok, encoded = cv2.imencode(".png", image)
    except cv2.error as error:
        raise ImageEncodeError(f"cannot encode PNG: {destination}") from error
    if not encoded_ok:
        raise ImageEncodeError(f"cannot encode PNG: {destination}")
    try:
        destination.write_bytes(encoded.tobytes())
    except OSError as error:
        raise ImageEncodeError(f"cannot write PNG: {destination}") from error
    return destination


def _is_bgr_image(image: object) -> bool:
    return (
        isinstance(image, np.ndarray)
        and image.dtype == np.uint8
        and image.ndim == 3
        and image.shape[2] == 3
        and image.shape[0] > 0
        and image.shape[1] > 0
    )
