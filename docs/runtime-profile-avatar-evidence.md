# Runtime profile-avatar compatibility evidence

M0.6b1b1 compares caller-supplied **player profile-avatar** crops within one session.  It never
uses a strategy initiator portrait, a display name, a player tag, a selection row, or a global
avatar database as visual identity.

`SessionProfileAvatarReference` contains a selection-side profile avatar and frame/source/pixel
provenance.  `RuntimeProfileAvatarObservation` contains an explicitly supplied ACTIVE runtime
player-card/avatar crop, its runtime slot ID, and the same provenance.  Both image payloads are
copied into immutable uint8 BGR arrays.

`derive_runtime_avatar_compatibility` creates an ephemeral, in-memory reference set for that
session only and reuses the local-feature SIFT/Lowe/RANSAC matcher.  Every geometrically accepted
selection participant stays in `candidate_session_player_ids`; it returns `unique`, `ambiguous`,
or `unresolved`.  It never chooses the strongest candidate among multiple accepted candidates.
The result's `avatar_candidate_participant_ids` can populate M0.6b1a's normalized avatar
candidate field, where other independent evidence may still be required.

The 1920x1080 JP MuMu calibration uses the full `121x119` runtime player-card crop and masks only
its fixed bottom `19px` HP/presentation overlay.  Selection profile crops are `92x92`.  The mask
is opt-in (`JP_MUMU_RUNTIME_CARD_BOTTOM_OVERLAY_EXCLUSION`) and is not an automatic viewport or
runtime-state detector.  No image is resized or modified for matching.

This evidence is session-local and non-persistent.  Runtime-state recognition, self-marker and
initial-HP evidence integration, and durable event/reducer integration remain separate work.
