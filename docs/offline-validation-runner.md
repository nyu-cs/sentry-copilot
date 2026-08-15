# Offline validation runner

M0.3a.3 provides the smallest development entry point for manually supplied local media:

```powershell
python -m sentry_copilot.cli validate-frames \
  --source .\synthetic-frames \
  --output .\outputs\validation \
  --full-frame \
  --sample-every 2 \
  --roi hud=0.05,0.05,0.25,0.15
```

`--source` must be an explicitly supplied image directory or local video path. The runner does
not scan `data/private/` or discover recordings. Use `--full-frame` or `--viewport X Y W H` to
choose the content viewport; no automatic viewport detection is performed.

The output contains selected frame debug images under `frames/`, named ROI crops under `rois/`,
and `manifest.jsonl`. Each manifest record includes frame identity/index, source timestamp,
frame size, viewport bounds, optional ROI name and pixel bounds, and the output path. Sampling
uses source frame indices and does not alter or mutate the immutable `Frame` objects.

This runner performs no OCR, template matching, page or player recognition, live capture, UI, or
automatic clicking.
