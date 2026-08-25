# Runtime player-card visual states

M0.6c1 observes only the presentation of caller-specified left-sidebar cards in the known
full-frame 1920×1080 JP MuMu layout.  It returns immutable visual evidence for `ACTIVE`,
`SPECTATING_OR_DEAD`, `EXITED`, or `UNRESOLVED`; it does not contain a participant ID, establish
battle entry, read player tags, or change a strategy/slot association.

The fixed cue is the upper `121×88` part of each `121×119` card.  The lower HP and presentation
area is excluded, so HP=0 is neither required nor used to recognize `SPECTATING_OR_DEAD`.
Calibration uses positive luminance-band footprints: an exited presentation needs a visible
low-band icon footprint; a spectating/dead presentation needs its persistent bright-gray icon
footprint; ACTIVE needs high-band profile-card detail.  A weak/dark crop without one of these
positive patterns is `UNRESOLVED`, never inferred from an absent inactive icon.

`project_runtime_player_card_state_to_association_core` is a pure adapter.  Resolved states map to
the association core's existing active, spectating/dead, or exited participation value.  An
unresolved observation leaves the input untouched.  The association core's existing sticky mapping
therefore retains a previously confirmed runtime slot → participant through `ACTIVE →
SPECTATING_OR_DEAD → EXITED` and direct `ACTIVE → EXITED` transitions; the visual recognizer never
rematches or asserts the participant identity.
