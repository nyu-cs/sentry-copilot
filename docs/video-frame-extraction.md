# Video frame extraction

`extract-video-frames` copies full-resolution PNG frames from exactly one caller-supplied local
video. It does not scan directories, crop, annotate, OCR, template-match, or interpret game UI.
All output is written only to the requested directory.

In Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m sentry_copilot.cli extract-video-frames --video data/private/live_validation/raw_video/session.mp4 --output data/private/live_validation/annotations/session_frames --at 00:00:15 strategy-selection --at 00:01:05 strategy-final --at 00:01:34 battle-entry
```

Each `--at` accepts `HH:MM:SS` or `HH:MM:SS.mmm` plus a path-safe label. The command seeks using
the source FPS to the nearest requested frame index, decodes one frame through OpenCV, and records
the actual decoded frame index and timestamp reported by OpenCV. Inter-frame codecs can make a
seek near-exact rather than byte-exact; the manifest preserves the decoded provenance.

The output directory contains one unmodified `TIMESTAMP_label.png` per successful request and
`video-frame-extraction.json`. Every manifest request has a typed `success` or `failed` status,
the exact video reference, requested and decoded timing, frame dimensions, output filename, and
failure details when applicable.
