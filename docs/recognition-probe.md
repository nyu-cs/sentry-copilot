# Recognition probe harness

M0.3c provides a small, game-agnostic developer utility for testing existing OCR and template
matching over exactly one explicitly selected frame. It does not discover inputs, ROIs, templates,
or game UI. All output goes to the caller-specified directory.

For a live monitor, select the physical monitor, wait for the desired screen, and declare each
operation explicitly. This example uses a full-frame normalized OCR crop, not a game coordinate:

```powershell
.\.venv\Scripts\python.exe -m sentry_copilot.cli recognition-probe --monitor 1 --start-delay-seconds 5 --output data/private/live_validation/sessions/jp_mumu_primary_recognition_probe_001 --language ja-JP --annotated-diagnostic --ocr-normalized-roi full_screen_text 0 0 1 1
```

For a caller-supplied local image and one caller-supplied template:

```powershell
.\.venv\Scripts\python.exe -m sentry_copilot.cli recognition-probe --image C:\work\synthetic-frame.png --output C:\work\probe-output --template-pixel-roi marker 10 20 120 80 C:\work\synthetic-template.png --annotated-diagnostic
```

Each operation is one of:

- `--ocr-normalized-roi NAME X Y WIDTH HEIGHT` or `--ocr-pixel-roi NAME X Y WIDTH HEIGHT`;
  all OCR operations require `--language`.
- `--template-normalized-roi NAME X Y WIDTH HEIGHT TEMPLATE` or
  `--template-pixel-roi NAME X Y WIDTH HEIGHT TEMPLATE`; templates are loaded only from their
  explicit paths. `--template-threshold` applies to template operations.

The output contains `source-frame.png`, one unannotated `roi-NAME.png` per operation, optional
`diagnostic.png`, and `recognition-probe.json`. The report records frame/source provenance,
requested and resolved ROI bounds, operation type, OCR language/result or template path/result,
and a typed `unavailable` or `failed` status when an operation cannot complete. A missing Windows
OCR language capability is reported as `unavailable`; the tool never installs language features.

The harness never scans `data/private/` or any other directory, reads only its explicit image or
template paths, and does not perform OCR parsing, page/slot/tag/strategy recognition, UI actions,
or automatic clicking.
