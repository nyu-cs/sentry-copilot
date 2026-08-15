# Frame sources and raw frame dumps

M0.3a.1 defines the capture/input boundary only. A `FrameSource` produces immutable BGR `Frame`
objects; it never locates a viewport, performs recognition, changes `SessionState`, or automates
input.

Every frame carries a stable source-local ID and index, a timezone-aware processing timestamp,
an optional relative source timestamp, source type/ID, dimensions, an immutable image payload,
and its source reference. The first implementations are `ImageSequenceFrameSource`,
`LocalVideoFrameSource`, and the read-only `WindowsDisplayFrameSource`. OpenCV is used only to
read and write local media; Windows display capture uses `mss`.

`dump_raw_frames(source, output_directory, session_id=...)` writes PNGs to the exact caller-owned
directory plus `frames.metadata.json`. The metadata records source identity, optional session ID,
dump time, and per-frame ID/index/timestamp/dimensions/file name. It creates no domain evidence or
recognition output.

The Windows display source accepts an explicit physical MSS monitor index (starting at one) and
uses the captured image's actual dimensions, so it does not use DPI-scaled logical coordinates.
It has no window-title tracking; a future `WindowsWindowFrameSource` can still implement
`FrameSource` without changing downstream consumers. Viewport calibration, ROI extraction, OCR,
template matching, page/player recognition, UI, and automatic clicking remain outside this
milestone. Tests use mocks and temporary synthetic images only; no private validation media is
read or tracked.
