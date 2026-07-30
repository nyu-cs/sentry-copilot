from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from sentry_copilot.domain.enums import EvidenceKind
from sentry_copilot.domain.evidence import EvidenceRecord
from sentry_copilot.domain.identifiers import LocaleId
from sentry_copilot.domain.models import SessionState
from sentry_copilot.domain.rulesets import (
    RevisionSelectionMethod,
    RevisionSelectionRecord,
    RulesetDependencyStamp,
    SessionRulesetContext,
)
from sentry_copilot.domain.strategy_selection import (
    EvidenceRecord as LegacyEvidenceRecord,
)
from sentry_copilot.domain.strategy_selection import StrategySelectionSnapshot

NOW = datetime(2026, 1, 1, tzinfo=UTC)
RULESET_ID = "sentry_protocol.covenant_latter"
EARLY_REVISION_ID = "sentry_protocol.covenant_latter.pre_update"
LATE_REVISION_ID = "sentry_protocol.covenant_latter.post_update"


def observed_evidence() -> EvidenceRecord:
    return EvidenceRecord(
        source=EvidenceKind.OBSERVED,
        confidence=0.95,
        observed_at=NOW,
    )


def unknown_context() -> SessionRulesetContext:
    return SessionRulesetContext(
        ruleset_id=RULESET_ID,
        locale_id=LocaleId.ZH_CN,
        selected_at=NOW,
    )


def selected_context(
    *,
    revision_id: str = EARLY_REVISION_ID,
    locale_id: LocaleId = LocaleId.ZH_CN,
    generation: int = 1,
    history: tuple[RevisionSelectionRecord, ...] = (),
) -> SessionRulesetContext:
    return SessionRulesetContext(
        ruleset_id=RULESET_ID,
        ruleset_revision_id=revision_id,
        locale_id=locale_id,
        catalog_version="catalog.synthetic.v1",
        selection_method=RevisionSelectionMethod.MANUAL,
        selected_at=NOW,
        selection_evidence=(observed_evidence(),),
        revision_history=history,
        context_generation=generation,
    )


def test_unknown_revision_context_starts_at_generation_zero() -> None:
    context = unknown_context()
    assert context.ruleset_revision_id is None
    assert context.catalog_version is None
    assert context.selection_method == RevisionSelectionMethod.UNKNOWN
    assert context.context_generation == 0
    assert context.dependency_stamp is None


def test_selected_revision_requires_positive_generation_and_catalog() -> None:
    with pytest.raises(ValidationError, match="positive context generation"):
        selected_context(generation=0)
    with pytest.raises(ValidationError, match="catalog_version"):
        SessionRulesetContext(
            ruleset_id=RULESET_ID,
            ruleset_revision_id=EARLY_REVISION_ID,
            locale_id=LocaleId.ZH_CN,
            selection_method=RevisionSelectionMethod.MANUAL,
            selected_at=NOW,
            context_generation=1,
        )


def test_unknown_to_selected_context_uses_next_generation() -> None:
    assert unknown_context().context_generation == 0
    assert selected_context().context_generation == 1


def test_revision_history_contains_every_replaced_generation_in_order() -> None:
    first_selection = RevisionSelectionRecord(
        ruleset_revision_id=EARLY_REVISION_ID,
        catalog_version="catalog.synthetic.v1",
        selection_method=RevisionSelectionMethod.MANUAL,
        selected_at=NOW,
        replaced_at=NOW + timedelta(minutes=1),
        context_generation=1,
    )
    context = selected_context(
        revision_id=LATE_REVISION_ID,
        generation=2,
        history=(first_selection,),
    )
    assert context.context_generation == 2
    assert context.revision_history == (first_selection,)

    with pytest.raises(ValidationError, match="each replaced context generation"):
        selected_context(revision_id=LATE_REVISION_ID, generation=2)


def test_dependency_stamp_includes_locale_and_generation() -> None:
    context = selected_context(locale_id=LocaleId.JA_JP)
    assert context.dependency_stamp == RulesetDependencyStamp(
        ruleset_id=RULESET_ID,
        ruleset_revision_id=EARLY_REVISION_ID,
        locale_id=LocaleId.JA_JP,
        catalog_version="catalog.synthetic.v1",
        context_generation=1,
    )
    assert context.dependency_stamp is not None
    assert context.dependency_stamp.model_dump()["locale_id"] == LocaleId.JA_JP


def test_ruleset_context_and_history_are_immutable() -> None:
    context = selected_context()
    with pytest.raises(ValidationError, match="frozen"):
        context.context_generation = 2
    with pytest.raises(AttributeError):
        context.revision_history.append(
            RevisionSelectionRecord(
                ruleset_revision_id=EARLY_REVISION_ID,
                catalog_version="catalog.synthetic.v1",
                selection_method=RevisionSelectionMethod.MANUAL,
                selected_at=NOW,
                replaced_at=NOW,
                context_generation=1,
            )
        )


def test_ruleset_context_rejects_naive_datetime() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        SessionRulesetContext(
            ruleset_id=RULESET_ID,
            locale_id=LocaleId.ZH_CN,
            selected_at=datetime(2026, 1, 1),
        )


@pytest.mark.parametrize(
    "invalid_ruleset_id",
    ["卫戍协议：盟约 下半", "SENTRY_PROTOCOL.COVENANT", 38],
)
def test_normalized_ruleset_id_rejects_display_names_and_non_strings(
    invalid_ruleset_id: object,
) -> None:
    with pytest.raises(ValidationError):
        SessionRulesetContext.model_validate(
            {
                "ruleset_id": invalid_ruleset_id,
                "locale_id": "zh_CN",
                "selected_at": NOW,
            }
        )


def test_context_populates_omitted_legacy_mirrors() -> None:
    state = SessionState(
        session_id="session.synthetic",
        ruleset_context=selected_context(locale_id=LocaleId.JA_JP),
    )
    assert state.ruleset_id == RULESET_ID
    assert state.locale == "ja_JP"
    assert state.effective_ruleset_id == RULESET_ID
    assert state.effective_locale_id == LocaleId.JA_JP
    assert state.effective_ruleset_revision_id == EARLY_REVISION_ID
    assert state.ruleset_dependency_stamp == state.ruleset_context.dependency_stamp


def test_context_accepts_matching_explicit_legacy_mirrors() -> None:
    state = SessionState(
        session_id="session.synthetic",
        ruleset_id=RULESET_ID,
        locale="zh_CN",
        ruleset_context=selected_context(),
    )
    assert state.ruleset_context is not None
    assert state.ruleset_context.ruleset_id == state.ruleset_id


@pytest.mark.parametrize(
    ("legacy_field", "legacy_value"),
    [
        ("ruleset_id", "demo.wrong"),
        ("locale", "ja_JP"),
    ],
)
def test_context_rejects_mismatched_explicit_legacy_mirrors(
    legacy_field: str,
    legacy_value: str,
) -> None:
    payload = {
        "session_id": "session.synthetic",
        "ruleset_context": selected_context(),
        legacy_field: legacy_value,
    }
    with pytest.raises(ValidationError, match="explicit legacy"):
        SessionState.model_validate(payload)


def test_assignment_cannot_desynchronize_legacy_mirrors() -> None:
    state = SessionState(
        session_id="session.synthetic",
        ruleset_context=selected_context(),
    )
    with pytest.raises(ValidationError, match="legacy locale"):
        state.locale = "ja_JP"
    with pytest.raises(ValidationError, match="legacy ruleset_id"):
        state.ruleset_id = "demo.wrong"
    assert state.locale == "zh_CN"
    assert state.ruleset_id == RULESET_ID


def test_contextless_session_keeps_m0_1a_construction_compatible() -> None:
    state = SessionState(
        session_id="session.synthetic",
        ruleset_id="demo.v1",
        locale="zh_CN",
    )
    assert state.ruleset_context is None
    assert state.effective_ruleset_id == "demo.v1"
    assert state.effective_ruleset_revision_id is None


def test_snapshot_ruleset_must_match_authoritative_context() -> None:
    snapshot = StrategySelectionSnapshot(
        session_id="session.synthetic",
        ruleset_id="demo.wrong",
        captured_at=NOW,
    )
    with pytest.raises(ValidationError, match="strategy selection ruleset_id"):
        SessionState(
            session_id="session.synthetic",
            ruleset_context=selected_context(),
            strategy_selection=snapshot,
        )


def test_ruleset_context_round_trips_through_python_and_json() -> None:
    context = selected_context(locale_id=LocaleId.JA_JP)
    assert SessionRulesetContext.model_validate(context.model_dump()) == context
    assert SessionRulesetContext.model_validate_json(context.model_dump_json()) == context


def test_legacy_evidence_import_reexports_shared_model() -> None:
    assert LegacyEvidenceRecord is EvidenceRecord
