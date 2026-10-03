# Live Encounter Intelligence

## Product contract

The desktop assistant maintains exactly four encounter information items:

1. Difficulty
2. Boss
3. Enemy Types
4. Banned Covenants

Complete supported progress is `4 / 4`. Banned Covenants is one item, complete only when both
the Major/Core and Additional snapshots are complete. A partial Ban component remains visible
without completing the combined item.

The primary calibrated profile is the Japanese client on Windows MuMu at 1920x1080.
The desktop shell supports English and Chinese locale modes independently of the Japanese
recognition profile. Some game entity names retain Chinese/localized catalog labels when no
deliberate English display name exists. The application is read-only: scrolling, returning to
INFO, and game navigation are performed by the user.

## Ownership

`LiveEncounterPreviewController` owns capture processing, page/lifecycle interpretation,
pending temporal candidates, recovery context, and the current `EncounterSession`.
The encounter session is not the strategy/player `SessionState` and is not managed by its reducer.

Visual observers return immutable observations with provenance. Session update functions validate
candidate identities and structure before recording facts. Presentation derives four-item
progress and localized content; Tk widgets do not decide which facts are confirmed.

Captured facts are sticky through absent, partial, or unresolved frames. A conflicting capture
does not silently overwrite a confirmed value. A confirmed new encounter creates a clean session;
capture loss alone does not.

## Encounter lifecycle

The initial `情報確認 1/2` (INFO 1/2) page is the start boundary. Genuine initial INFO requires
the page observation and at least one reliable initial enemy identity. The first genuine initial
observation starts the first encounter; individual facts retain their own temporal gates.

For subsequent encounters, three consecutive genuine absent observations arm departure.
Three consecutive strict canonical next-initial observations then promote a new encounter.
That classifier checks page/layout structure and reliable enemy evidence and excludes same-frame
returned INFO and INFO 2/2. Generic INFO-like transitions are insufficient.

Returned INFO and INFO 2/2 enrich or guide the existing encounter; they are not start boundaries.
Production does not use the broader outside-run END path to discard the session. Capture
disconnect/retry preserves the current encounter and its armed lifecycle state.

## Difficulty, Boss, and Enemy Types

Difficulty candidates come from calibrated visual cues for Standard / AC-1, Adversity / AC-2,
Deadland / AC-3, and Ultimate / AC-4. Initial INFO uses visual color evidence under page/lifecycle
authorization and two-frame confirmation; it does not add a separate color-score-margin gate.

Post-start difficulty recovery uses the calibrated OPERATION splash and INFO 2/2 top-bar cues.
It enriches the same encounter and reports contradictions without changing encounter identity.
The live path does not use OCR for difficulty.

Boss and enemy recognition use explicitly loaded visual references and catalog identities.
Initial Boss capture requires three consecutive matching reliable candidates. Initial Enemy
Types are captured directly from one complete reliable observation with a resolved two- or
three-slot layout and non-null enemy IDs, without a two-frame controller debounce or accumulation
of unrelated partial frames. Returned INFO uses its own recovery surfaces and confirmation
counters (two matching candidates for Boss and complete Enemy Types) to fill missing facts
without replacing already captured values.

## Major/Core Covenant recognition

Initial and returned INFO support Major/Core recognition on AC-2, AC-3, and AC-4.
Initial AC-4 / Ultimate Major capture is implemented; it is not disabled.

Eight Major disc identities must be distinct and complete, with five unrestricted and three
disabled. Nominal positions locate discs but never determine their identities. Shape-based
recentering, an inner-disc crop, and saturation-based state polarity precede glyph recognition.
Cached SIFT features and homography RANSAC provide identity scores.

The bounded identity gates are unchanged:

- at least 10 RANSAC inliers for the top candidate;
- a top-one minus top-two score margin of at least 10.

On initial INFO, an unresolved nominal query can try eight local center offsets from
`(-2, 0, 2)` pixels on each axis, excluding `(0, 0)`. Each alternative must pass the same
identity gates. Refinement is accepted only when all reliable alternatives agree on one
identity; competing identities leave the original observation unresolved. This is bounded
crop refinement, not a lowered threshold or identity-by-position fallback.

A complete reliable row still requires two matching disabled-ID sets before capture.
Returned Major recovery has its own locator/context gate and fills only a missing snapshot.

## Additional Covenant recognition

Additional recognition is implemented for AC-2, AC-3, and AC-4 on initial INFO and authorized
returned-INFO scans. Its reference pack declares all 15 Additional identities exactly once.
A complete structural interpretation has 11 unrestricted and four disabled Covenants.

The observer uses bounded search regions, circle geometry, saturation polarity, SIFT glyph
features, and RANSAC evidence. Glyph rankings must have a unique best score; positions constrain
layout only and never provide an identity. The full-layout path accepts the supported nine-plus-six
arrangement. The lower-row path uses canonical six-slot geometry, including a bounded five-of-six
case whose inferred crop still has to pass identity and geometry checks.

Partial/clipped rows, competing logical rows, duplicate identities, unresolved polarity, and
ambiguous glyph rankings do not create a complete snapshot. Two matching complete four-ID
disabled sets are required before persistence. Confirmed results remain sticky.

This is not universal scroll robustness. At extreme low-row scroll positions the second row can
fall outside accepted geometry or usable crop bounds and remain unresolved. No forced fallback
is applied; public tests cover bounded acceptance/rejection cases, not every private live frame.

## Returned-INFO recovery

After initial departure, two consecutive INFO 2/2 observations can show a reminder for supported
missing facts/components. Returning to INFO hides that reminder and arms a scan of the existing
encounter. Boss/enemy recovery requires the recognized returned page; Covenant scans can continue
through scrolling that moves its header out of view.

The scan context is controller-owned and does not treat an isolated missing header as a new
encounter. INFO 2/2, a confirmed new encounter, or recovery closure resets the appropriate scan
state. Reliable OPERATION closes recovery for the run without ending or replacing the encounter.

Recovery fills missing Boss, Enemy Types, Major, and Additional facts under their individual
gates. Difficulty has its separate post-start recovery path. Captured values are retained; a
revisit never implies that the game changed its bans.

## Bans presentation and operator projection

Major and Additional snapshots are stored independently and presented together. Complete Bans
has three Major plus four Additional disabled identities. Standard / AC-1 is explicitly
unsupported for Bans and retains the same four-item progress denominator.

Operator projection is a pure catalog query. An ordinary operator is confirmed banned only
when every static recruitment route is known, disableable, and disabled. An unknown route or
a non-disableable support route blocks that conclusion. Dynamic Ultimate rules are kept
separate from static membership edges rather than guessed.

Ban Detail presents Major rows before Additional rows and wraps operator cards at seven per
row. Existing `name_zh_CN` and `portrait_key` contracts are preserved. Optional local
portraits and neutral Covenant icons are presentation resources, not recognition references;
missing media can fall back to text.

## Running and diagnostics

From an editable checkout with private reference packs and an installed MuMu renderer IPC DLL:

```powershell
python -m sentry_copilot.cli live-encounter-preview `
  --capture-backend mumu-ipc `
  --mumu-install-root '<MuMu install root>' `
  --mumu-ipc-dll '<path to external_renderer_ipc.dll>' `
  --mumu-instance-id 0 `
  --mumu-display-id 0 `
  --locale en
```

MuMu capture targets approximately five frames per second; that is a target, not a throughput
guarantee. Physical-display capture is a secondary option with explicit monitor selection.

The panel shows running/waiting/error status, profile/build information, and Copy Diagnostics.
`--diagnostic-output path\to\diagnostic.json` writes local diagnostic JSON after the window
closes. The preview does not upload diagnostics or record gameplay. MuMu IPC captures the game
framebuffer directly, excluding the desktop assistant window. The physical-display fallback
captures the selected monitor, so assistant windows or other overlays can enter recognition
input if they overlap calibrated game-content/ROI areas.

Reference loaders use declared private paths rather than directory discovery. Missing assets do
not establish recognition support. See [Validation boundaries](validation.md) and
[Third-party notices](../THIRD_PARTY_NOTICES.md).
