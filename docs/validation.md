# Validation boundaries

## Public reproducibility

From an editable Python 3.12+ checkout:

```bash
pytest
ruff check .
python -m mypy
python tools/validate_repository.py
git diff --check
sentry-copilot demo-encounter --headless
python -m sentry_copilot.cli validate-data --maps data/maps
python -m sentry_copilot.cli demo-route-overlay --map-file data/maps/demo.synthetic_training_map.yaml --output outputs/demo_route_overlay.png
```

GitHub Actions runs pytest, Ruff, strict mypy, repository validation, the source-checkout
synthetic demo, and an isolated build/install/run check of the wheel on Ubuntu/Python 3.12.
A configured workflow is not a claim about the status of an uninspected remote run.

The public suite uses synthetic pixels, typed observations, fake capture/native adapters,
temporary catalogs, and pure presentation helpers. It covers evidence idempotence/corrections,
revision freshness, commitment/occupancy conflicts, participation, runtime association,
encounter lifecycle and returned-INFO gates, sticky captures, bounded Major/Additional cases,
operator projection, UI layout state, and route projection/rendering.

The synthetic encounter timeline runs without private resources or Tk and exercises the same
session updates/presentation used by the GUI demo, not visual observers or live recovery gates.
Its source categories represent simulated INFO surfaces; no frames are recognized.
The synthetic route image is a projection demonstration, not a verified game route.
Synthetic strategy-catalog validation establishes fixture consistency only. Support-target
declarations and bootstrap catalog metadata are not validated real-revision support.

## Private calibrated evidence

Real encounter development used private live and retained frames on the Japanese MuMu
1920x1080 profile. Recognition loaders depend on explicit local reference packs under
`data/private/`; those assets and recordings are not part of public test reproducibility.

The implementation and public tests establish bounded algorithm/state contracts, not a
recognition success rate across all gameplay, scroll offsets, languages, or resolutions.
In particular, initial AC-4 Major uses bounded local crop refinement with unchanged identity
thresholds, while Additional can remain unresolved at extreme low-row positions.

No new live validation is implied by a documentation-only change. Do not describe old private
checks as comprehensive public evidence or infer game mechanics from video titles,
thumbnails, or unreviewed notes.

## Local diagnostics and probes

CLI tools support explicitly supplied media and ROIs, including `validate-frames`,
`recognition-probe`, `visual-catalog-match`, and `visual-local-feature-match`.
Capture/recognition probes can write local debug images and reports; the encounter preview's
optional diagnostic JSON does not record gameplay or upload data.

Keep outputs and source media in ignored local directories and review provenance/permissions
before publication. See [Frame sources](frame-sources.md),
[Offline validation runner](offline-validation-runner.md), and
[Third-party notices](../THIRD_PARTY_NOTICES.md).
