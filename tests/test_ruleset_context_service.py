from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from sentry_copilot.catalogs.repository import (
    LoadedStrategyCatalog,
    StrategyCatalogRepository,
    load_catalog,
)
from sentry_copilot.domain.commands import (
    CorrectSessionRulesetRevision,
    SelectSessionRulesetContext,
)
from sentry_copilot.domain.enums import EvidenceKind
from sentry_copilot.domain.evidence import EvidenceRecord
from sentry_copilot.domain.identifiers import LocaleId
from sentry_copilot.domain.models import SessionState
from sentry_copilot.domain.queries import (
    get_current_ruleset_dependency_stamp,
    get_session_ruleset_context,
)
from sentry_copilot.domain.rulesets import (
    RevisionSelectionMethod,
    RulesetDependencyStamp,
    SessionRulesetContext,
)
from sentry_copilot.domain.strategy import (
    ProtocolRuleset,
    RulesetRevision,
    StrategyCatalog,
)
from sentry_copilot.domain.strategy_selection import StrategySelectionSnapshot
from sentry_copilot.services.ruleset_context_service import (
    RulesetContextCommandError,
    RulesetContextErrorCode,
    RulesetContextService,
)

CATALOG_PATH = Path(
    "data/strategy_catalogs/demo.synthetic_covenant_latter/catalog.yaml"
)
CATALOG_VERSION = "catalog.synthetic.v1"
SECOND_CATALOG_VERSION = "catalog.synthetic.v2"
RULESET_ID = "demo.synthetic_covenant_latter"
EARLY_REVISION = "demo.synthetic_covenant_latter.pre_update"
LATE_REVISION = "demo.synthetic_covenant_latter.post_update"
OTHER_RULESET_ID = "demo.synthetic_other"
OTHER_REVISION = "demo.synthetic_other.pre_update"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def repository() -> StrategyCatalogRepository:
    return StrategyCatalogRepository.from_directory("data/strategy_catalogs")


@pytest.fixture
def service(repository: StrategyCatalogRepository) -> RulesetContextService:
    return RulesetContextService(repository)


def selection_evidence(
    *,
    observed_at: datetime = NOW,
    detail: str = "synthetic manual ruleset selection",
) -> EvidenceRecord:
    return EvidenceRecord(
        source=EvidenceKind.MANUAL,
        confidence=1.0,
        observed_at=observed_at,
        source_detail=detail,
    )


def select_command(
    *,
    revision_id: str = EARLY_REVISION,
    catalog_version: str = CATALOG_VERSION,
    locale_id: LocaleId = LocaleId.ZH_CN,
    selected_at: datetime = NOW,
    method: RevisionSelectionMethod = RevisionSelectionMethod.MANUAL,
    ruleset_id: str = RULESET_ID,
    reason: str = "synthetic initial selection",
) -> SelectSessionRulesetContext:
    return SelectSessionRulesetContext(
        session_id="session.synthetic",
        ruleset_id=ruleset_id,
        ruleset_revision_id=revision_id,
        locale_id=locale_id,
        catalog_version=catalog_version,
        selection_method=method,
        selected_at=selected_at,
        selection_evidence=(
            selection_evidence(observed_at=selected_at),
        ),
        reason=reason,
    )


def correction_command(
    *,
    revision_id: str = LATE_REVISION,
    catalog_version: str = CATALOG_VERSION,
    locale_id: LocaleId = LocaleId.ZH_CN,
    selected_at: datetime = NOW + timedelta(minutes=1),
    ruleset_id: str = RULESET_ID,
    reason: str = "synthetic explicit correction",
) -> CorrectSessionRulesetRevision:
    return CorrectSessionRulesetRevision(
        session_id="session.synthetic",
        ruleset_id=ruleset_id,
        ruleset_revision_id=revision_id,
        locale_id=locale_id,
        catalog_version=catalog_version,
        selected_at=selected_at,
        selection_evidence=(
            selection_evidence(
                observed_at=selected_at,
                detail="synthetic correction evidence",
            ),
        ),
        reason=reason,
    )


def bare_state(
    *,
    snapshot: StrategySelectionSnapshot | None = None,
) -> SessionState:
    return SessionState(
        session_id="session.synthetic",
        ruleset_id=snapshot.ruleset_id if snapshot is not None else "unknown",
        strategy_selection=snapshot,
    )


def unknown_state() -> SessionState:
    return SessionState(
        session_id="session.synthetic",
        ruleset_context=SessionRulesetContext(
            ruleset_id=RULESET_ID,
            locale_id=LocaleId.ZH_CN,
            selected_at=NOW,
            selection_evidence=(
                selection_evidence(detail="synthetic unknown evidence"),
            ),
            selection_reason="synthetic revision pending",
        ),
    )


def selected_state(service: RulesetContextService) -> SessionState:
    return service.select(bare_state(), select_command())


def dual_version_repository() -> StrategyCatalogRepository:
    loaded = load_catalog(CATALOG_PATH)
    second_catalog = StrategyCatalog.model_validate(
        {
            **loaded.catalog.model_dump(),
            "catalog_version": SECOND_CATALOG_VERSION,
        }
    )
    return StrategyCatalogRepository(
        (
            loaded,
            LoadedStrategyCatalog(
                catalog=second_catalog,
                asset_root=loaded.asset_root,
            ),
        )
    )


def multi_ruleset_repository() -> StrategyCatalogRepository:
    loaded = load_catalog(CATALOG_PATH)
    expanded_catalog = StrategyCatalog.model_validate(
        {
            **loaded.catalog.model_dump(),
            "rulesets": (
                *loaded.catalog.rulesets,
                ProtocolRuleset(
                    ruleset_id=OTHER_RULESET_ID,
                    revision_ids=frozenset({OTHER_REVISION}),
                    supported_locales=frozenset({LocaleId.ZH_CN}),
                ),
            ),
            "revisions": (
                *loaded.catalog.revisions,
                RulesetRevision(
                    ruleset_revision_id=OTHER_REVISION,
                    ruleset_id=OTHER_RULESET_ID,
                    revision_order=0,
                ),
            ),
        }
    )
    return StrategyCatalogRepository(
        (
            LoadedStrategyCatalog(
                catalog=expanded_catalog,
                asset_root=loaded.asset_root,
            ),
        )
    )


def assert_rejected_without_change(
    state: SessionState,
    *,
    code: RulesetContextErrorCode,
    operation,
) -> None:
    before = state.model_dump(mode="json")
    with pytest.raises(RulesetContextCommandError) as exc_info:
        operation()
    assert exc_info.value.code == code
    assert state.model_dump(mode="json") == before


def test_manual_initial_selection_without_context(
    service: RulesetContextService,
) -> None:
    original = bare_state()
    result = service.select(original, select_command())
    assert original.ruleset_context is None
    assert result.ruleset_context is not None
    assert result.ruleset_context.ruleset_revision_id == EARLY_REVISION
    assert result.ruleset_context.selection_method == RevisionSelectionMethod.MANUAL
    assert result.ruleset_context.context_generation == 1
    assert result.ruleset_context.revision_history == ()
    assert result.ruleset_id == RULESET_ID
    assert result.locale == "zh_CN"


def test_replay_metadata_uses_initial_selection_flow(
    service: RulesetContextService,
) -> None:
    result = service.select(
        bare_state(),
        select_command(
            method=RevisionSelectionMethod.IMPORTED_FROM_REPLAY_METADATA,
            reason="synthetic replay metadata",
        ),
    )
    assert result.ruleset_context is not None
    assert (
        result.ruleset_context.selection_method
        == RevisionSelectionMethod.IMPORTED_FROM_REPLAY_METADATA
    )
    assert result.ruleset_context.context_generation == 1


def test_auto_detection_is_not_an_initial_selection_method() -> None:
    with pytest.raises(ValidationError, match="manual or imported"):
        select_command(method=RevisionSelectionMethod.AUTO_DETECTED)


def test_context_commands_reject_naive_selection_time() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        SelectSessionRulesetContext.model_validate(
            {
                **select_command().model_dump(),
                "selected_at": datetime(2026, 1, 1),
            }
        )


def test_unknown_context_to_concrete_preserves_unknown_history(
    service: RulesetContextService,
) -> None:
    original = unknown_state()
    result = service.select(
        original,
        select_command(selected_at=NOW + timedelta(minutes=1)),
    )
    assert result.ruleset_context is not None
    assert result.ruleset_context.context_generation == 1
    assert len(result.ruleset_context.revision_history) == 1
    unknown_record = result.ruleset_context.revision_history[0]
    assert unknown_record.ruleset_revision_id is None
    assert unknown_record.catalog_version is None
    assert unknown_record.selection_method == RevisionSelectionMethod.UNKNOWN
    assert unknown_record.context_generation == 0
    assert unknown_record.selected_at == NOW
    assert unknown_record.replaced_at == NOW + timedelta(minutes=1)
    assert unknown_record.reason == "synthetic revision pending"
    assert unknown_record.evidence == original.ruleset_context.selection_evidence


def test_unknown_then_correction_keeps_contiguous_history_generations(
    service: RulesetContextService,
) -> None:
    selected = service.select(
        unknown_state(),
        select_command(selected_at=NOW + timedelta(minutes=1)),
    )
    corrected = service.correct(
        selected,
        correction_command(selected_at=NOW + timedelta(minutes=2)),
    )
    assert corrected.ruleset_context is not None
    assert corrected.ruleset_context.context_generation == 2
    assert tuple(
        record.context_generation
        for record in corrected.ruleset_context.revision_history
    ) == (0, 1)


def test_concrete_context_cannot_use_initial_selection_again(
    service: RulesetContextService,
) -> None:
    state = selected_state(service)
    assert_rejected_without_change(
        state,
        code=RulesetContextErrorCode.RULESET_CONTEXT_ALREADY_SELECTED,
        operation=lambda: service.select(
            state,
            select_command(
                revision_id=LATE_REVISION,
                selected_at=NOW + timedelta(minutes=1),
            ),
        ),
    )


def test_unknown_context_cannot_use_correction(
    service: RulesetContextService,
) -> None:
    state = unknown_state()
    assert_rejected_without_change(
        state,
        code=RulesetContextErrorCode.RULESET_REVISION_UNKNOWN,
        operation=lambda: service.correct(state, correction_command()),
    )


def test_correction_requires_an_existing_context(
    service: RulesetContextService,
) -> None:
    state = bare_state()
    assert_rejected_without_change(
        state,
        code=RulesetContextErrorCode.RULESET_CONTEXT_NOT_SELECTED,
        operation=lambda: service.correct(state, correction_command()),
    )


def test_early_to_late_correction_appends_previous_selection(
    service: RulesetContextService,
) -> None:
    state = selected_state(service)
    result = service.correct(state, correction_command())
    assert result.ruleset_context is not None
    assert result.ruleset_context.ruleset_revision_id == LATE_REVISION
    assert result.ruleset_context.context_generation == 2
    assert len(result.ruleset_context.revision_history) == 1
    previous = result.ruleset_context.revision_history[0]
    assert previous.ruleset_revision_id == EARLY_REVISION
    assert previous.selected_at == NOW
    assert previous.replaced_at == NOW + timedelta(minutes=1)
    assert previous.reason == "synthetic initial selection"


def test_early_late_early_uses_a_new_generation(
    service: RulesetContextService,
) -> None:
    first_early = selected_state(service)
    late = service.correct(first_early, correction_command())
    second_early = service.correct(
        late,
        correction_command(
            revision_id=EARLY_REVISION,
            selected_at=NOW + timedelta(minutes=2),
        ),
    )
    assert first_early.ruleset_dependency_stamp is not None
    assert second_early.ruleset_dependency_stamp is not None
    assert first_early.ruleset_dependency_stamp.ruleset_revision_id == EARLY_REVISION
    assert second_early.ruleset_dependency_stamp.ruleset_revision_id == EARLY_REVISION
    assert first_early.ruleset_dependency_stamp.context_generation == 1
    assert second_early.ruleset_dependency_stamp.context_generation == 3
    assert first_early.ruleset_dependency_stamp != second_early.ruleset_dependency_stamp


def test_correction_count_has_no_domain_limit(
    service: RulesetContextService,
) -> None:
    state = selected_state(service)
    for index in range(1, 9):
        revision_id = LATE_REVISION if index % 2 else EARLY_REVISION
        state = service.correct(
            state,
            correction_command(
                revision_id=revision_id,
                selected_at=NOW + timedelta(minutes=index),
            ),
        )
    assert state.ruleset_context is not None
    assert state.ruleset_context.context_generation == 9
    assert len(state.ruleset_context.revision_history) == 8
    assert tuple(
        record.context_generation
        for record in state.ruleset_context.revision_history
    ) == tuple(range(1, 9))


def test_identical_context_is_typed_rejection_without_new_history(
    service: RulesetContextService,
) -> None:
    state = selected_state(service)
    assert_rejected_without_change(
        state,
        code=RulesetContextErrorCode.IDENTICAL_CONTEXT,
        operation=lambda: service.correct(
            state,
            correction_command(
                revision_id=EARLY_REVISION,
                selected_at=NOW + timedelta(minutes=1),
            ),
        ),
    )


def test_same_revision_new_catalog_is_explicit_correction() -> None:
    service = RulesetContextService(dual_version_repository())
    state = selected_state(service)
    result = service.correct(
        state,
        correction_command(
            revision_id=EARLY_REVISION,
            catalog_version=SECOND_CATALOG_VERSION,
        ),
    )
    assert result.ruleset_context is not None
    assert result.ruleset_context.ruleset_revision_id == EARLY_REVISION
    assert result.ruleset_context.catalog_version == SECOND_CATALOG_VERSION
    assert result.ruleset_context.context_generation == 2
    assert result.ruleset_context.revision_history[0].catalog_version == CATALOG_VERSION


def test_revision_from_another_ruleset_is_rejected() -> None:
    service = RulesetContextService(multi_ruleset_repository())
    state = selected_state(service)
    assert_rejected_without_change(
        state,
        code=RulesetContextErrorCode.INVALID_REVISION_FOR_RULESET,
        operation=lambda: service.correct(
            state,
            correction_command(revision_id=OTHER_REVISION),
        ),
    )


def test_unknown_catalog_version_is_rejected_atomically(
    service: RulesetContextService,
) -> None:
    state = selected_state(service)
    assert_rejected_without_change(
        state,
        code=RulesetContextErrorCode.CATALOG_VERSION_MISMATCH,
        operation=lambda: service.correct(
            state,
            correction_command(catalog_version="catalog.synthetic.unknown"),
        ),
    )


def test_revision_missing_from_catalog_is_rejected(
    service: RulesetContextService,
) -> None:
    state = selected_state(service)
    assert_rejected_without_change(
        state,
        code=RulesetContextErrorCode.RULESET_REVISION_UNKNOWN,
        operation=lambda: service.correct(
            state,
            correction_command(
                revision_id="demo.synthetic_covenant_latter.missing",
            ),
        ),
    )


def test_catalog_without_requested_ruleset_is_rejected(
    service: RulesetContextService,
) -> None:
    state = bare_state()
    assert_rejected_without_change(
        state,
        code=RulesetContextErrorCode.CATALOG_MISMATCH,
        operation=lambda: service.select(
            state,
            select_command(
                ruleset_id="demo.synthetic_missing",
                revision_id=EARLY_REVISION,
            ),
        ),
    )


def test_correction_cannot_change_locale(
    service: RulesetContextService,
) -> None:
    state = selected_state(service)
    assert_rejected_without_change(
        state,
        code=RulesetContextErrorCode.LOCALE_MISMATCH,
        operation=lambda: service.correct(
            state,
            correction_command(locale_id=LocaleId.JA_JP),
        ),
    )


def test_correction_cannot_change_ruleset() -> None:
    service = RulesetContextService(multi_ruleset_repository())
    state = selected_state(service)
    assert_rejected_without_change(
        state,
        code=RulesetContextErrorCode.RULESET_MISMATCH,
        operation=lambda: service.correct(
            state,
            correction_command(
                ruleset_id=OTHER_RULESET_ID,
                revision_id=OTHER_REVISION,
            ),
        ),
    )


def test_mismatch_check_never_auto_switches_revision(
    service: RulesetContextService,
) -> None:
    state = selected_state(service)
    assert_rejected_without_change(
        state,
        code=RulesetContextErrorCode.RULESET_REVISION_MISMATCH,
        operation=lambda: service.validate_current_context(
            state,
            ruleset_id=RULESET_ID,
            ruleset_revision_id=LATE_REVISION,
            locale_id=LocaleId.ZH_CN,
            catalog_version=CATALOG_VERSION,
        ),
    )


def test_catalog_mismatch_check_never_changes_state(
    service: RulesetContextService,
) -> None:
    state = selected_state(service)
    assert_rejected_without_change(
        state,
        code=RulesetContextErrorCode.CATALOG_VERSION_MISMATCH,
        operation=lambda: service.validate_current_context(
            state,
            ruleset_id=RULESET_ID,
            ruleset_revision_id=EARLY_REVISION,
            locale_id=LocaleId.ZH_CN,
            catalog_version=SECOND_CATALOG_VERSION,
        ),
    )


def test_failed_correction_does_not_increment_generation(
    service: RulesetContextService,
) -> None:
    state = selected_state(service)
    generation = state.ruleset_context.context_generation
    with pytest.raises(RulesetContextCommandError):
        service.correct(
            state,
            correction_command(catalog_version="catalog.synthetic.unknown"),
        )
    assert state.ruleset_context.context_generation == generation


def test_selection_time_cannot_move_backwards(
    service: RulesetContextService,
) -> None:
    state = selected_state(service)
    assert_rejected_without_change(
        state,
        code=RulesetContextErrorCode.INVALID_SELECTION_TIME,
        operation=lambda: service.correct(
            state,
            correction_command(selected_at=NOW - timedelta(seconds=1)),
        ),
    )


def test_legacy_mirrors_update_atomically(
    service: RulesetContextService,
) -> None:
    selected = selected_state(service)
    corrected = service.correct(selected, correction_command())
    assert selected.ruleset_id == corrected.ruleset_id == RULESET_ID
    assert selected.locale == corrected.locale == "zh_CN"
    assert corrected.ruleset_context is not None
    assert corrected.ruleset_context.ruleset_id == corrected.ruleset_id
    assert corrected.ruleset_context.locale_id.value == corrected.locale


def test_successful_correction_preserves_prebattle_snapshot_and_evidence(
    service: RulesetContextService,
) -> None:
    snapshot = StrategySelectionSnapshot(
        session_id="session.synthetic",
        ruleset_id=RULESET_ID,
        captured_at=NOW,
        evidence=(
            selection_evidence(detail="synthetic prebattle evidence"),
        ),
    )
    initial = service.select(bare_state(snapshot=snapshot), select_command())
    corrected = service.correct(initial, correction_command())
    assert corrected.strategy_selection == snapshot
    assert corrected.strategy_selection.evidence == snapshot.evidence
    assert corrected.ruleset_context is not None
    assert corrected.ruleset_context.revision_history[0].evidence == (
        selection_evidence(),
    )


def test_dependency_stamp_query_contains_locale_and_does_not_mutate_state(
    service: RulesetContextService,
) -> None:
    state = selected_state(service)
    before = state.model_dump(mode="json")
    context = get_session_ruleset_context(state)
    stamp = get_current_ruleset_dependency_stamp(state)
    assert context is state.ruleset_context
    assert stamp == RulesetDependencyStamp(
        ruleset_id=RULESET_ID,
        ruleset_revision_id=EARLY_REVISION,
        locale_id=LocaleId.ZH_CN,
        catalog_version=CATALOG_VERSION,
        context_generation=1,
    )
    assert state.model_dump(mode="json") == before


def test_context_queries_return_none_before_selection() -> None:
    state = bare_state()
    before = state.model_dump(mode="json")
    assert get_session_ruleset_context(state) is None
    assert get_current_ruleset_dependency_stamp(state) is None
    assert state.model_dump(mode="json") == before


def test_context_and_unknown_history_round_trip_through_session_json(
    service: RulesetContextService,
) -> None:
    state = service.select(
        unknown_state(),
        select_command(selected_at=NOW + timedelta(minutes=1)),
    )
    restored = SessionState.model_validate_json(state.model_dump_json())
    assert restored.ruleset_context == state.ruleset_context
    assert restored.ruleset_context is not None
    assert restored.ruleset_context.revision_history[0].context_generation == 0


def test_session_mismatch_is_rejected_before_any_change(
    service: RulesetContextService,
) -> None:
    state = bare_state()
    command = select_command().model_copy(update={"session_id": "session.other"})
    assert_rejected_without_change(
        state,
        code=RulesetContextErrorCode.SESSION_MISMATCH,
        operation=lambda: service.select(state, command),
    )
