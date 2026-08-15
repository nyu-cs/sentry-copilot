# Frame sources and raw frame dumps

M0.3a.1 defines the capture/input boundary only. A `FrameSource` produces immutable BGR `Frame`
objects; it never locates a viewport, performs recognition, changes `SessionState`, or automates
input.

Every frame carries a stable source-local ID and index, a timezone-aware processing timestamp,
an optional relative source timestamp, source type/ID, dimensions, an immutable image payload,
and its source reference. The first implementations are `ImageSequenceFrameSource` and
`LocalVideoFrameSource`; OpenCV is used only to read and write local media.

`dump_raw_frames(source, output_directory, session_id=...)` writes PNGs to the exact caller-owned
directory plus `frames.metadata.json`. The metadata records source identity, optional session ID,
dump time, and per-frame ID/index/timestamp/dimensions/file name. It creates no domain evidence or
recognition output.

The interface is intentionally independent of where frames originate. A future
`WindowsWindowFrameSource` can implement `FrameSource` without changing downstream recognizers.
Windows capture, viewport calibration, ROI extraction, OCR, template matching, page/player
recognition, UI, and automatic clicking remain outside this milestone. Tests create temporary
synthetic images and video only; no private validation media is read or tracked.
