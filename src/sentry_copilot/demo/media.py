"""Project-authored procedural Ban Detail media; no downloads, files, or game artwork."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

import cv2
import numpy as np
import numpy.typing as npt

from sentry_copilot.encounter.presentation import EncounterPanelView


@dataclass(frozen=True)
class DemoEncounterMedia:
    """Immutable BGRA pixels keyed by the identities used by the production renderer."""

    covenant_icons: Mapping[str, npt.NDArray[np.uint8]]
    operator_portraits: Mapping[str, npt.NDArray[np.uint8]]


def _covenant_icon(index: int) -> npt.NDArray[np.uint8]:
    """Draw one of seven distinct neutral 40px outline glyphs on transparent pixels."""

    image = np.zeros((40, 40, 4), dtype=np.uint8)
    ink = (55, 55, 55, 255)
    style = index % 7
    if style == 0:
        cv2.circle(image, (20, 20), 13, ink, 3, cv2.LINE_AA)
    elif style in {1, 2, 4, 5}:
        vertices = {
            1: ((20, 4), (36, 20), (20, 36), (4, 20)),
            2: ((20, 5), (35, 34), (5, 34)),
            4: ((7, 7), (33, 7), (33, 33), (7, 33)),
            5: ((20, 4), (34, 12), (34, 28), (20, 36), (6, 28), (6, 12)),
        }
        cv2.polylines(image, [np.array(vertices[style], dtype=np.int32)], True, ink, 3, cv2.LINE_AA)
    elif style == 3:
        cv2.line(image, (8, 8), (32, 32), ink, 3, cv2.LINE_AA)
        cv2.line(image, (32, 8), (8, 32), ink, 3, cv2.LINE_AA)
    else:
        cv2.line(image, (20, 5), (20, 35), ink, 3, cv2.LINE_AA)
        cv2.line(image, (5, 20), (35, 20), ink, 3, cv2.LINE_AA)
    image.setflags(write=False)
    return image


def _operator_portrait(index: int) -> npt.NDArray[np.uint8]:
    """Draw a fictional 60px silhouette with a large A-D identifier, not a game character."""

    backgrounds = (
        (225, 220, 212, 255),
        (214, 228, 226, 255),
        (222, 218, 230, 255),
        (224, 225, 215, 255),
    )
    image = np.empty((60, 60, 4), dtype=np.uint8)
    image[:] = backgrounds[index % 4]
    ink = (80, 75, 70, 255)
    cv2.rectangle(image, (1, 1), (58, 58), ink, 1, cv2.LINE_AA)
    cv2.circle(image, (30, 18), 9, ink, -1, cv2.LINE_AA)
    cv2.ellipse(image, (30, 57), (23, 22), 0, 180, 360, ink, -1, cv2.LINE_AA)
    letter = chr(65 + index)
    size, _baseline = cv2.getTextSize(letter, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
    cv2.putText(
        image,
        letter,
        ((60 - size[0]) // 2, 54),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (250, 250, 250, 255),
        2,
        cv2.LINE_AA,
    )
    image.setflags(write=False)
    return image


def build_demo_media(view: EncounterPanelView) -> DemoEncounterMedia:
    """Generate GUI-only media keyed consistently across repeated synthetic row entries."""

    rows = view.confirmed_banned_operator_rows
    operator_ids = sorted({card.operator_id for row in rows for card in row.operators})
    return DemoEncounterMedia(
        covenant_icons=MappingProxyType(
            {row.covenant_id: _covenant_icon(index) for index, row in enumerate(rows)}
        ),
        operator_portraits=MappingProxyType(
            {
                operator_id: _operator_portrait(index)
                for index, operator_id in enumerate(operator_ids)
            }
        ),
    )
