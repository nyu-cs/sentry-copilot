# Content viewport and normalized ROI

M0.3a.2 adds geometry-only vision primitives that consume an immutable capture `Frame` without
creating observations or touching domain state. A caller must explicitly supply a
`ContentViewport`; automatic black-bar, window-shell, or viewport detection is intentionally out
of scope.

`ContentViewport` is bound to a particular frame ID and raw dimensions. It can represent an
arbitrary game-content rectangle or an explicit full-frame viewport. This keeps downstream ROI
coordinates independent of desktop position, emulator chrome, DPI scaling, black bars, and raw
frame resolution.

`NormalizedRoi` uses `[0, 1]` coordinates relative to the content viewport. Resolving it produces
a bounded `PixelRoi` in raw-frame coordinates. Cropping makes a fresh read-only image payload, so
the source `Frame` remains unchanged. `save_roi_debug_image` writes an annotated copy only to the
caller-selected destination; it does not modify the frame or infer game UI.

No OCR, template matching, page recognition, slot/tag/ready recognition, capture source, or user
interface is implemented here.
