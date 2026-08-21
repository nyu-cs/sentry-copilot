# Local-feature visual matching

M0.4c adds a second, independent visual matcher for cross-layout portrait evidence. The original
template matcher remains the preferred small primitive when reference and query use nearly
identical rendering geometry. It is not removed or behaviorally changed.

Cross-layout renders may contain the same identity artwork at different isotropic scales,
translations, crop framing, brightness, and UI resampling. `LocalFeatureVisualMatcher` addresses
that case with this shared pipeline:

```text
explicit BGR query crop
    -> SIFT keypoints/descriptors
    -> Lowe-ratio descriptor matches
    -> similarity transform estimated by RANSAC
    -> scale/rotation/inlier validation
    -> strongest reference per catalog identity
    -> matched / unresolved / ambiguous
```

The matcher consumes the existing `VisualReferenceCatalog`; it does not own strategy or avatar
identities and does not define another asset manifest. Multiple render-context references for one
identity are legal and aggregate to the strongest valid reference. They never create ambiguity
with themselves. Ambiguity is possible only between different identity IDs.

## Evidence and geometry

Every reference candidate retains query/reference keypoint counts, raw and Lowe-ratio match
counts, RANSAC inliers, inlier ratio, asset hash/provenance, reference kind, catalog schema version,
and catalog fingerprint. The estimated similarity transform is explicitly **query to reference**:

- scale is unitless and isotropic;
- rotation is in degrees;
- X/Y translation is measured in reference-image pixels.

The score is `RANSAC inliers / query keypoints`. It is an inlier ratio, not a probability or
calibrated confidence. The defaults reproduce the seven-anchor feasibility experiment:

- SIFT `nfeatures=300`, `contrastThreshold=0.02`, `edgeThreshold=10`;
- Lowe ratio `0.75`;
- RANSAC reprojection threshold `3 px`;
- accepted scale `0.80..1.60` and absolute rotation at most `5 degrees`;
- at least three RANSAC inliers.

The default minimum inlier ratio and ambiguity margin are intentionally non-calibrating foundation
values. Callers may provide an explicit minimum ratio and ambiguity margin. If no reference forms
valid geometric consensus, the result is `unresolved`. If different identities fall within the
configured ambiguity margin, the result is `ambiguous` and no identity is selected.

Reference SIFT descriptors are computed once when a matcher instance loads a catalog and remain an
in-memory cache for subsequent queries. The catalog and its declared assets remain authoritative;
M0.4c does not add a persistent descriptor database.

## Developer CLI

The command reads only the explicit catalog, its declared assets, and the explicit query path. It
does not scan directories.

```powershell
.\.venv\Scripts\python.exe -m sentry_copilot.cli visual-local-feature-match `
  --kind strategy `
  --catalog data/private/visual_catalogs/strategy-references.yaml `
  --image data/private/queries/strategy-crop.png `
  --output data/private/live_validation/local-feature-match
```

Optional flags expose every matcher parameter, including `--minimum-inlier-ratio` and
`--ambiguity-margin`. The output `visual-local-feature-match.json` records the exact configuration,
ranked identity candidates, every reference candidate, transform evidence, query hash and
dimensions, and catalog fingerprint.

The current real validation covers seven cross-layout strategy anchors only. Its successful result
does not imply that all 40 strategies, all rendering contexts, or player avatars are validated.
Full-catalog negative testing and threshold calibration must occur before production recognition
uses the result as confirmed identity evidence.
