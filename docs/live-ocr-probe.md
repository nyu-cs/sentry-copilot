# Live OCR probe

M0.3b.3 is a developer smoke-test utility for the existing read-only Windows physical-display
source and source-neutral OCR foundation. It has no game recognition rules. The user explicitly
selects the physical MSS monitor, BCP-47 OCR language, one normalized or pixel ROI, optional delay,
and the only output directory.

Check local OCR support without changing Windows features:

```powershell
python -m sentry_copilot.cli check-ocr-language --language ja-JP
```

Capture exactly one frame and OCR exactly one normalized ROI:

```powershell
python -m sentry_copilot.cli live-ocr-probe --monitor 1 --language ja-JP --start-delay-seconds 5 --normalized-roi 0 0 1 1 --output outputs/live_ocr_probe
```

The output directory contains `captured-frame.png`, an unannotated `roi-crop.png`, and
`ocr-result.json`. The JSON preserves raw and normalized text, OCR status, language, resolved pixel
ROI, and complete frame/source provenance. If the requested Windows OCR capability is absent, the
probe still saves the frame and crop, then records an `ocr_unavailable` outcome and typed reason.
It does not install language packs, scan private directories, inspect other frames, parse
`name#XXXX`, or perform page, strategy, ready, or slot recognition.
