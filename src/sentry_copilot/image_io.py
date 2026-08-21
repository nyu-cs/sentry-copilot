"""Small Unicode-safe local image decoding helpers.

The helper reads exactly one caller-supplied path and decodes it as an unchanged
uint8 BGR image.  Reading bytes before OpenCV decoding avoids Windows path
encoding limitations in ``cv2.imread``.
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


def load_bgr_image(path: str | Path) -> BgrImage:
    """Decode exactly one image path as an unchanged three-channel BGR payload."""

    source = Path(path)
    try:
        encoded = source.read_bytes()
    except OSError as error:
        raise ImageDecodeError(f"cannot read image: {source}") from error

    image = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise ImageDecodeError(f"cannot decode image: {source}")
    return cast(BgrImage, image)
