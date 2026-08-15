from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import cv2
import numpy as np
import pytest

from sentry_copilot.capture.frame_source import (
    Frame,
    FrameSource,
    FrameSourceType,
    ImageSequenceFrameSource,
    LocalVideoFrameSource,
    dump_raw_frames,
)


def _image(value: int) -> np.ndarray[tuple[int, int, int], np.dtype[np.uint8]]:
    return np.full((4, 6, 3), value, dtype=np.uint8)


def _write_image(path: Path, value: int) -> None:
    assert cv2.imwrite(str(path), _image(value))


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


def test_image_sequence_yields_immutable_stable_frames(tmp_path: Path) -> None:
    first = tmp_path / "frame_002.png"
    second = tmp_path / "frame_010.png"
    _write_image(first, 10)
    _write_image(second, 200)
    source = ImageSequenceFrameSource((first, second), source_id="synthetic-images")

    frames = tuple(source.frames())

    assert isinstance(source, FrameSource)
    assert [frame.frame_id for frame in frames] == [
        "synthetic-images:000000",
        "synthetic-images:000001",
    ]
    assert [frame.frame_index for frame in frames] == [0, 1]
    assert all(frame.source_type == FrameSourceType.IMAGE_SEQUENCE for frame in frames)
    assert all(frame.source_timestamp is None for frame in frames)
    assert all(frame.processed_at.tzinfo is not None for frame in frames)
    assert [(frame.width, frame.height) for frame in frames] == [(6, 4), (6, 4)]
    assert all(not frame.image.flags.writeable for frame in frames)
    with pytest.raises(ValueError):
        frames[0].image[0, 0, 0] = 1


def test_image_sequence_directory_uses_stable_lexical_order(tmp_path: Path) -> None:
    _write_image(tmp_path / "frame_010.png", 10)
    _write_image(tmp_path / "frame_002.png", 200)

    frames = tuple(ImageSequenceFrameSource.from_directory(tmp_path).frames())

    assert [Path(frame.source_reference).name for frame in frames] == [
        "frame_002.png",
        "frame_010.png",
    ]


def test_local_video_uses_source_timestamps_and_open_cv_io(tmp_path: Path) -> None:
    video_path = tmp_path / "synthetic.avi"
    _write_video(video_path)
    source = LocalVideoFrameSource(video_path, source_id="synthetic-video")

    frames = tuple(source.frames())

    assert [frame.frame_index for frame in frames] == [0, 1, 2]
    assert [frame.timestamp_seconds for frame in frames] == pytest.approx([0.0, 0.2, 0.4])
    assert all(frame.source_type == FrameSourceType.LOCAL_VIDEO for frame in frames)
    assert all(frame.source_reference == str(video_path) for frame in frames)
    assert all(not frame.image.flags.writeable for frame in frames)


def test_local_video_can_sample_without_changing_frame_indices(tmp_path: Path) -> None:
    video_path = tmp_path / "synthetic.avi"
    _write_video(video_path)

    frames = tuple(
        LocalVideoFrameSource(video_path, sample_every_seconds=0.4).frames()
    )

    assert [frame.frame_index for frame in frames] == [0, 2]


def test_raw_dump_writes_requested_directory_and_minimal_metadata(tmp_path: Path) -> None:
    first = tmp_path / "source_1.png"
    second = tmp_path / "source_2.png"
    _write_image(first, 10)
    _write_image(second, 20)
    destination = tmp_path / "requested-dump"
    source = ImageSequenceFrameSource((first, second), source_id="synthetic-dump")

    result = dump_raw_frames(
        source,
        destination,
        session_id="session.synthetic",
        processed_at=datetime(2026, 8, 15, tzinfo=UTC),
    )

    assert result.output_directory == destination
    assert [path.name for path in result.frame_paths] == [
        "frame_000000.png",
        "frame_000001.png",
    ]
    assert all(path.is_file() for path in result.frame_paths)
    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["session_id"] == "session.synthetic"
    assert metadata["source"]["source_id"] == "synthetic-dump"
    assert metadata["source"]["source_type"] == "image_sequence"
    assert [item["frame_index"] for item in metadata["frames"]] == [0, 1]


def test_frame_rejects_naive_processing_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        Frame(
            frame_id="synthetic:000000",
            frame_index=0,
            processed_at=datetime(2026, 8, 15),
            source_timestamp=None,
            source_type=FrameSourceType.IMAGE_SEQUENCE,
            source_id="synthetic",
            width=6,
            height=4,
            image=_image(1),
            source_reference="synthetic.png",
        )


def test_frame_defensively_owns_its_image_payload() -> None:
    original = _image(1)
    frame = Frame(
        frame_id="synthetic:000000",
        frame_index=0,
        processed_at=datetime(2026, 8, 15, tzinfo=UTC),
        source_timestamp=None,
        source_type=FrameSourceType.IMAGE_SEQUENCE,
        source_id="synthetic",
        width=6,
        height=4,
        image=original,
        source_reference="synthetic.png",
    )

    original[0, 0, 0] = 99

    assert frame.image[0, 0, 0] == 1
