# Runtime preparation checkpoints

M0.6b1b2 adds a small, frame-only evidence path for the known full-frame 1920x1080 JP MuMu
layout.  It does not create player identity, runtime participation, a `SessionState` mirror, or
a complete game-phase state machine.

## Conservative phase and round evidence

`observe_jp_mumu_preparation_checkpoint` accepts an immutable `Frame`, explicit full-frame
`ContentViewport`, caller-owned runtime-slot visual positions, and an injected OCR backend.  It
uses the fixed top-center `休憩タイム` label as the sole positive `PREPARATION` signal.  A clearly
OCR-readable battle enemy count such as `37/37` is sufficient only for `NOT_PREPARATION`.
Anything else is `UNRESOLVED`.

It deliberately does **not** infer preparation from the shop/card UI, missing left-card
exclamation marks, or a missing individual battle control.  Those signals may vary while the
local player is inspecting a teammate field or during joint defense.

The displayed round number is independently typed.  A numeric OCR result is accepted only when
it is exact.  The observed single-glyph round-one presentation has a narrowly calibrated shape
fallback because Windows OCR can leave that solitary digit empty.  Other OCR failures remain
unresolved; the feature never substitutes frame order, timestamps, or a presumed first frame.

## Runtime self and HP observations

For the same layout, a runtime card is an explicit geometry (`34, 211 + 145 * (visual_index -
1), 121x119`).  A fixed upper-left teal self-marker region produces one of
`SELF_MARKER_PRESENT`, `SELF_MARKER_ABSENT`, or `UNRESOLVED`.  At checkpoint aggregation, exactly
one present marker is usable.  Zero remains unresolved and multiple present markers form a
conflict; no score or display order chooses a winner.

The bottom-card HP ROI is OCR-only current-state evidence.  It records `OBSERVED`, `UNRESOLVED`,
or `INVALID` with all fixed crop/evidence variants and does not label the raw value as initial
HP.  A strict exact result wins over incidental one-digit clipping artefacts; inconsistent
two-/three-digit results remain invalid rather than being ranked.

Runtime profile avatars remain a separate signal.  They are player-profile imagery, not strategy
initiator portraits, and are not compared to a strategy visual by this feature.

## Initial-HP history and association projection

`derive_runtime_initial_hp_evidence` consumes caller-supplied chronological checkpoints for one
session.  A value establishes `known_initial_hp` **only** when both conditions hold:

- the checkpoint is confidently `PREPARATION`; and
- its independently observed `round_number` is exactly `1`.

Round-one preparation is pre-loss.  A later checkpoint can update `current_hp` and expose
`hp_loss_observed`, but can never backfill or overwrite the historical baseline.  If round-one
preparation was missed, `known_initial_hp` stays unknown.

`RuntimeInitialHpEvidence.project_to_association_core` supplies only that historical baseline to
M0.6b1a's existing `hp_is_known_initial` filter.  It never feeds a reduced later current HP into
association.  Likewise, `project_unique_self_marker_to_association_core` projects a self claim
only after the checkpoint aggregate is unique.  Both are immutable query adapters; neither
persists a second association authority.

## Deferred scope

This is not runtime-state recognition.  Battle, joint defense, settlement, inactivation,
spectating/departure, leak counts, active-team coverage, player-tag OCR, strategy-panel fallback,
and automatic input remain outside M0.6b1b2.  Later M0.6c work can add redundant battle/settlement
evidence without changing the round-one baseline contract.
