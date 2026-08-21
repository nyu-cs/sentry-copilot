from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from sentry_copilot.capture.video_frame_extraction import (
    VideoFrameExtractionConfig,
    VideoFrameExtractionStatus,
    VideoFrameRequest,
    extract_video_frames,
    parse_video_timestamp,
)
from sentry_copilot.cli import build_parser


def _image(value: int) -> np.ndarray[tuple[int, int, int], np.dtype[np.uint8]]:
    return np.full((4, 6, 3), value, dtype=np.uint8)


def _write_video(path: Path) -> None:
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        5.0,
        (6, 4),
    )
    if not writer.isOpened():
        pytest.skip("synthetic OpenCV video writer is unavailable")
    try:
        for value in (10, 80, 150):
            writer.write(_image(value))
    finally:
        writer.release()


def test_extracts_explicit_full_resolution_frames_and_manifest(tmp_path: Path) -> None:
    video_path = tmp_path / "synthetic.avi"
    output_directory = tmp_path / "requested-output"
    _write_video(video_path)

    result = extract_video_frames(
        VideoFrameExtractionConfig(
            video_path=video_path,
            output_directory=output_directory,
            requests=(
                VideoFrameRequest("00:00:00", "selection"),
                VideoFrameRequest("00:00:00.400", "battle-entry"),
            ),
        )
    )

    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert result.frame_rate == pytest.approx(5.0)
    assert [record.status for record in result.records] == [
        VideoFrameExtractionStatus.SUCCESS,
        VideoFrameExtractionStatus.SUCCESS,
    ]
    assert [
        record.output_path.name for record in result.records if record.output_path is not None
    ] == [
        "00-00-00_selection.png",
        "00-00-00-400_battle-entry.png",
    ]
    assert all(
        record.output_path is not None and record.output_path.is_file() for record in result.records
    )
    assert [
        cv2.imread(str(record.output_path), cv2.IMREAD_COLOR).shape for record in result.records
    ] == [
        (4, 6, 3),
        (4, 6, 3),
    ]
    assert payload["source_video_path"] == str(video_path)
    assert payload["requests"][0]["status"] == "success"
    assert payload["requests"][0]["actual_decoded_frame_index"] == 0
    assert payload["requests"][1]["actual_decoded_frame_index"] == 2
    assert payload["requests"][1]["width"] == 6
    assert payload["requests"][1]["height"] == 4


def test_open_failure_is_written_as_typed_manifest_outcomes(tmp_path: Path) -> None:
    missing = tmp_path / "missing.mp4"
    output_directory = tmp_path / "requested-output"

    result = extract_video_frames(
        VideoFrameExtractionConfig(
            video_path=missing,
            output_directory=output_directory,
            requests=(VideoFrameRequest("00:00:15", "selection"),),
        )
    )

    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert result.records[0].status is VideoFrameExtractionStatus.FAILED
    assert result.records[0].failure_type == "VideoOpenError"
    assert payload["requests"][0]["failure"]["type"] == "VideoOpenError"
    assert payload["requests"][0]["output_filename"] is None


@pytest.mark.parametrize(
    ("value", "seconds"),
    [("00:00:15", 15.0), ("01:02:03.004", 3723.004)],
)
def test_timestamp_parser_accepts_the_supported_forms(value: str, seconds: float) -> None:
    assert parse_video_timestamp(value).total_seconds() == pytest.approx(seconds)


@pytest.mark.parametrize("value", ["1:02:03", "00:60:00", "00:00:60", "00:00:01.1"])
def test_timestamp_parser_rejects_noncanonical_or_invalid_values(value: str) -> None:
    with pytest.raises(ValueError, match="timestamp"):
        parse_video_timestamp(value)


def test_cli_accepts_repeated_explicit_timestamp_requests() -> None:
    args = build_parser().parse_args(
        [
            "extract-video-frames",
            "--video",
            "synthetic.avi",
            "--output",
            "requested-output",
            "--at",
            "00:00:15",
            "strategy-selection",
            "--at",
            "00:01:05",
            "strategy-final",
        ]
    )

    assert args.command == "extract-video-frames"
    assert args.video == Path("synthetic.avi")
    assert args.at == [["00:00:15", "strategy-selection"], ["00:01:05", "strategy-final"]]
