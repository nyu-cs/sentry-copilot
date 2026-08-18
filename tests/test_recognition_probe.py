from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import cv2
import numpy as np
import pytest

from sentry_copilot.capture.frame_source import (
    Frame,
    FrameSource,
    FrameSourceMetadata,
    FrameSourceType,
    ImageArray,
)
from sentry_copilot.cli import build_parser
from sentry_copilot.vision.ocr import OcrBackendReading, OcrBackendUnavailableError
from sentry_copilot.vision.recognition_probe import (
    OcrProbeOperation,
    RecognitionProbeConfig,
    RecognitionProbeConfigurationError,
    RecognitionProbeStatus,
    TemplateProbeOperation,
    load_template_image,
    run_recognition_probe,
)
from sentry_copilot.vision.template_matching import TemplateImage
from sentry_copilot.vision.viewport import NormalizedRoi, PixelRoi


class _StaticFrameSource(FrameSource):
    def __init__(self, frame: Frame) -> None:
        self.frame = frame
        self.closed = False

    @property
    def metadata(self) -> FrameSourceMetadata:
        return FrameSourceMetadata(
            source_id="synthetic-probe",
            source_type=FrameSourceType.IMAGE_SEQUENCE,
            source_reference="synthetic-probe.png",
        )

    def frames(self) -> Iterator[Frame]:
        try:
            yield self.frame
        finally:
            self.closed = True


class _ReadingBackend:
    def __init__(self) -> None:
        self.images: list[ImageArray] = []
        self.languages: list[str] = []

    async def recognize(self, image: ImageArray, *, language_tag: str) -> OcrBackendReading:
        self.images.append(image)
        self.languages.append(language_tag)
        return OcrBackendReading(" synthetic 日本語 0038 ", confidence=0.9)


class _UnavailableBackend:
    async def recognize(self, image: ImageArray, *, language_tag: str) -> OcrBackendReading:
        del image
        raise OcrBackendUnavailableError(f"missing language capability: {language_tag}")


def _frame() -> Frame:
    image = np.zeros((20, 30, 3), dtype=np.uint8)
    image[7:11, 12:17] = np.array(
        [
            [[10, 20, 30], [20, 30, 40], [30, 40, 50], [40, 50, 60], [50, 60, 70]],
            [[20, 40, 60], [30, 50, 70], [40, 60, 80], [50, 70, 90], [60, 80, 100]],
            [[30, 60, 90], [40, 70, 100], [50, 80, 110], [60, 90, 120], [70, 100, 130]],
            [[40, 80, 120], [50, 90, 130], [60, 100, 140], [70, 100, 140], [80, 120, 160]],
        ],
        dtype=np.uint8,
    )
    return Frame(
        frame_id="synthetic-probe:000007",
        frame_index=7,
        processed_at=datetime(2026, 8, 18, tzinfo=UTC),
        source_timestamp=timedelta(seconds=1.5),
        source_type=FrameSourceType.IMAGE_SEQUENCE,
        source_id="synthetic-probe",
        width=30,
        height=20,
        image=image,
        source_reference="synthetic-probe.png",
    )


def _template(frame: Frame) -> TemplateImage:
    return TemplateImage("template.synthetic.marker", frame.image[7:11, 12:17])


def test_probe_runs_multiple_explicit_operations_and_writes_a_diagnostic_report(
    tmp_path: Path,
) -> None:
    frame = _frame()
    original = np.array(frame.image, copy=True)
    source = _StaticFrameSource(frame)
    backend = _ReadingBackend()
    delays: list[float] = []

    result = run_recognition_probe(
        source,
        RecognitionProbeConfig(
            output_directory=tmp_path / "probe",
            operations=(
                OcrProbeOperation("jp-text", NormalizedRoi(0, 0, 0.5, 0.5), "ja-JP"),
                TemplateProbeOperation(
                    "marker",
                    PixelRoi(8, 4, 16, 12),
                    _template(frame),
                    "synthetic/template-marker.png",
                    threshold=0.99,
                ),
            ),
            start_delay_seconds=2.0,
            write_annotated_diagnostic=True,
        ),
        ocr_backend=backend,
        sleeper=delays.append,
    )

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    ocr, template = payload["operations"]
    assert result.source_frame_path.is_file()
    assert result.diagnostic_path is not None and result.diagnostic_path.is_file()
    assert [item.status for item in result.operations] == [
        RecognitionProbeStatus.COMPLETED,
        RecognitionProbeStatus.COMPLETED,
    ]
    assert payload["source"] == {
        "frame_id": frame.frame_id,
        "frame_index": 7,
        "height": 20,
        "processed_at": "2026-08-18T00:00:00+00:00",
        "source_id": "synthetic-probe",
        "source_reference": "synthetic-probe.png",
        "source_timestamp_seconds": 1.5,
        "source_type": "image_sequence",
        "width": 30,
    }
    assert ocr["operation_type"] == "ocr"
    assert ocr["requested_roi"] == {
        "kind": "normalized",
        "x": 0,
        "y": 0,
        "width": 0.5,
        "height": 0.5,
    }
    assert ocr["ocr"] == {
        "confidence": 0.9,
        "language_tag": "ja-JP",
        "normalized_text": "synthetic 日本語 0038",
        "raw_text": " synthetic 日本語 0038 ",
        "status": "recognized",
    }
    assert template["operation_type"] == "template"
    assert template["template"]["template_id"] == "template.synthetic.marker"
    assert template["template"]["template_reference"] == "synthetic/template-marker.png"
    assert template["template"]["matched"]
    assert template["template"]["match_bounds"] == {"x": 12, "y": 7, "width": 5, "height": 4}
    assert all(Path(operation["crop_path"]).is_file() for operation in payload["operations"])
    assert backend.languages == ["ja-JP"]
    assert backend.images[0].shape == (10, 15, 3)
    assert not backend.images[0].flags.writeable
    assert delays == [2.0]
    assert source.closed
    assert np.array_equal(frame.image, original)


def test_unavailable_ocr_is_typed_without_stopping_other_probe_operations(tmp_path: Path) -> None:
    frame = _frame()
    source = _StaticFrameSource(frame)

    result = run_recognition_probe(
        source,
        RecognitionProbeConfig(
            output_directory=tmp_path / "probe",
            operations=(
                OcrProbeOperation("jp-text", PixelRoi(0, 0, 10, 10), "ja-JP"),
                TemplateProbeOperation(
                    "marker",
                    PixelRoi(8, 4, 16, 12),
                    _template(frame),
                    "synthetic/template-marker.png",
                ),
            ),
        ),
        ocr_backend=_UnavailableBackend(),
    )

    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert result.operations[0].status is RecognitionProbeStatus.UNAVAILABLE
    assert result.operations[1].status is RecognitionProbeStatus.COMPLETED
    assert payload["operations"][0]["failure"] == {
        "message": "missing language capability: ja-JP",
        "type": "OcrBackendUnavailableError",
    }
    assert payload["operations"][1]["template"]["matched"]


def test_explicit_template_loader_reads_only_the_selected_synthetic_file(tmp_path: Path) -> None:
    frame = _frame()
    path = tmp_path / "template.png"
    assert cv2.imwrite(str(path), frame.image[7:11, 12:17])

    template = load_template_image(path, template_id="template.synthetic.loaded")

    assert template.template_id == "template.synthetic.loaded"
    assert template.image.shape == (4, 5, 3)
    assert not template.image.flags.writeable


def test_probe_configuration_rejects_implicit_or_duplicate_operations(tmp_path: Path) -> None:
    operation = OcrProbeOperation("text", PixelRoi(0, 0, 1, 1), "ja-JP")

    with pytest.raises(RecognitionProbeConfigurationError, match="at least one"):
        RecognitionProbeConfig(tmp_path, ())
    with pytest.raises(RecognitionProbeConfigurationError, match="must be unique"):
        RecognitionProbeConfig(tmp_path, (operation, operation))


def test_cli_accepts_explicit_multi_operation_definitions() -> None:
    args = build_parser().parse_args(
        [
            "recognition-probe",
            "--image",
            "synthetic-frame.png",
            "--output",
            "synthetic-output",
            "--language",
            "ja-JP",
            "--ocr-normalized-roi",
            "text",
            "0",
            "0",
            "1",
            "1",
            "--template-pixel-roi",
            "marker",
            "1",
            "2",
            "3",
            "4",
            "synthetic-template.png",
        ]
    )

    assert args.command == "recognition-probe"
    assert args.image == Path("synthetic-frame.png")
    assert args.ocr_normalized_roi == [["text", "0", "0", "1", "1"]]
    assert args.template_pixel_roi == [["marker", "1", "2", "3", "4", "synthetic-template.png"]]
