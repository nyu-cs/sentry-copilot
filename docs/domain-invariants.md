# Domain invariants

These constraints describe maintained strategy/player and route contracts. They preserve the
technical rules formerly recorded alongside internal development instructions.
The live encounter product has a separate controller/session path; see
[Architecture](architecture.md).

## Participant identity and historical selection

- The left-side portrait is a personalized player avatar, not the selected strategy.
  Never derive or set `strategy_id` from `avatar_visual_key`.
- `player_tag` is a session-local four-digit string, not a global account identifier.
  Selection rows are not runtime slots; never bind them by order.
- Strategy selection is the primary prebattle acquisition source. Its reducer-owned
  `StrategySelectionSnapshot` is an immutable historical materialized view, not runtime
  strategy-assignment authority.
- A snapshot has at most four participants. Completeness is legacy field coverage relative to
  an explicit `expected_participant_count` of `entered_battle` participants, never inferred
  from the number of observed rows. Repeated legacy strategy values are allowed.
- Runtime departure, disconnect, or elimination must not change historical selection outcomes,
  remove snapshot participants, change selected strategies, or change snapshot completeness.

## Ruleset and catalog authority

- `SessionRulesetContext` is the sole authority for new ruleset-, revision-, locale-, and
  catalog-aware strategy/player code. Legacy session/snapshot values are compatibility mirrors
  or assertions, not alternative authorities.
- The confirmed target name is `卫戍协议：盟约 下半`. Its pre-update and post-update
  revisions are separate data states; the name's suffix is not a revision.
- `StrategyIdentity` stores only the normalized ID. A `RulesetStrategyProfile` owns
  revision-specific icon mapping; locale resources never own icons.
- Revision selection/correction is an explicit command-service operation validated against
  catalogs. The generic reducer accepts validated facts and never loads YAML, accesses the
  filesystem, infers a revision, or silently switches context.
- A target-support declaration is not validated support. Synthetic validation proves the
  synthetic fixture, not a real game revision.
- Catalog-derived identification requires raw candidate evidence and the current dependency
  stamp. Direct/manual identification is generation-independent but must remain compatible
  with the current catalog.

## Evidence, commitment, and correction

- Raw prebattle candidates are evidence, not normalized strategy IDs or occupancy.
  Every evidence item has a stable ID; exact replay is idempotent.
- A visible ready check is per-player evidence of irreversible in-game selection.
  Repeated ready evidence does not create another commitment or move its first confirmation
  time. There is no game-domain unready or release transition.
- A false-positive correction preserves the observation and excludes it from effective evidence;
  it does not claim that a player cancelled ready in the game.
- Concrete identification is separate from raw evidence and commitment. A confirmed strategy
  has at most one valid occupant. Duplicate concrete claims are assistant conflicts: retain
  every claim, expose no contested occupancy, and require explicit correction.
- Legacy `StrategySelectionParticipant.strategy_id` may contain catalog-dependent
  interpretation. Preserve it through the explicit audited migration adapter, never as current
  identification, occupancy, or assignment.
- Migration is idempotent by operation ID and canonical snapshot fingerprint.
  `snapshot.frozen` closes only ordinary legacy merging, not evidence, correction, commitment,
  identification, or migration histories.

## Battle participation and runtime association

- Battle UI presence does not prove entry. Only reliable normal active participation produces
  `BATTLE_ENTRY_CONFIRMED`. A first stable frame already showing departure is
  entry-not-confirmed and creates no commitment, identification, or occupancy; prior ready
  evidence remains authoritative.
- Participation is `ACTIVE` or terminal `INACTIVE`. Assistant-record corrections are not
  in-game re-entry, reactivation, or revival.
- Active leave and disconnect share `LEFT_OR_DISCONNECTED`; do not make disconnect a separate
  business inactivation reason. The number below the portrait is health; `hp <= 0` means
  elimination and maps to HP depletion.
- Runtime slot identity is normalized within an explicit layout epoch. Visual index, selection
  row, legacy position, avatar, and HP are not stable participant-association identities.
  An uncertain reorder starts a new layout and inherits no associations.
- Durable slot association targets confirmed battle entrants only. Current claims derive from
  unsuperseded `DIRECT_PLAYER_TAG`, `DIRECT_SELF_MARKER`, or explicit manual confirmation.
  One-to-one conflicts remain unresolved, with no latest-write-wins or confidence winner.
- User-guided top-left panel fallback requires the user to select the player's portrait,
  switch to that field, open the panel, and capture it with explicit runtime context.
  Establish `runtime slot -> participant` from displayed `name#XXXX` before deriving
  participant strategy and slot assignment.
- Panel evidence must bind to an already associated participant. There is no slot-only strategy
  authority or `DIRECT_SLOT_STRATEGY_PANEL` bypass. All clicks remain manual.

The deterministic normalized association core is a separate query-style component. Its
avatar/pre-loss-HP constraints do not replace the durable direct association rules above.

## Routes and resource boundaries

- Every route is scoped by `ruleset_id` and `map_id`.
- Store route points in normalized battlefield coordinates, never fixed screen pixels.
- Low-confidence map recognition or calibration produces an explicit unknown result and no overlay.
- Do not commit game assets, third-party recordings, or unlicensed screenshots.
- Do not add input automation to the read-only product.

See [Data contracts](data-contracts.md), [Strategy selection](strategy-selection.md),
[Strategy identification](strategy-identification.md), [Battle roster](battle-roster.md),
[Runtime slots](runtime-slots.md), and [Route system](route-system.md) for detailed APIs.
