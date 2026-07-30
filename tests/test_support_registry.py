from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from sentry_copilot.catalogs.repository import load_support_registry
from sentry_copilot.catalogs.validation import (
    SupportRegistryValidationError,
    validate_support_registry,
)
from sentry_copilot.domain.identifiers import LocaleId
from sentry_copilot.domain.support import (
    SupportRegistry,
    SupportTarget,
    ValidationKind,
    ValidationOutcome,
    ValidationRecord,
)

SUPPORT_PATH = Path("data/strategy_catalogs/support-targets.yaml")
RULESET_ID = "sentry_protocol.covenant_latter"
EARLY_REVISION = "sentry_protocol.covenant_latter.pre_update"


def support_target() -> SupportTarget:
    return SupportTarget(
        ruleset_id=RULESET_ID,
        ruleset_revision_id=EARLY_REVISION,
        locale_id=LocaleId.ZH_CN,
    )


def validation_record() -> ValidationRecord:
    return ValidationRecord(
        ruleset_id=RULESET_ID,
        ruleset_revision_id=EARLY_REVISION,
        locale_id=LocaleId.ZH_CN,
        catalog_version="catalog.synthetic.v1",
        validation_kind=ValidationKind.CATALOG_STRUCTURE,
        outcome=ValidationOutcome.PASSED,
        validated_at=datetime(2026, 1, 1, tzinfo=UTC),
        evidence_references=("fixture.synthetic.catalog",),
    )


def test_public_registry_declares_four_targets_without_validated_support() -> None:
    registry = load_support_registry(SUPPORT_PATH)
    assert len(registry.targets) == 4
    assert registry.validation_records == ()
    assert registry.is_target(
        ruleset_id=RULESET_ID,
        ruleset_revision_id=EARLY_REVISION,
        locale_id=LocaleId.JA_JP,
    )
    assert registry.records_for(
        ruleset_id=RULESET_ID,
        ruleset_revision_id=EARLY_REVISION,
        locale_id=LocaleId.JA_JP,
    ) == ()


def test_validation_record_is_minimal_aware_and_round_trippable() -> None:
    record = validation_record()
    assert ValidationRecord.model_validate(record.model_dump()) == record
    assert ValidationRecord.model_validate_json(record.model_dump_json()) == record
    with pytest.raises(ValidationError, match="timezone"):
        ValidationRecord.model_validate(
            {
                **record.model_dump(),
                "validated_at": datetime(2026, 1, 1),
            }
        )


def test_registry_returns_records_without_promoting_support() -> None:
    target = support_target()
    record = validation_record()
    registry = SupportRegistry(targets=(target,), validation_records=(record,))
    assert registry.is_target(
        ruleset_id=target.ruleset_id,
        ruleset_revision_id=target.ruleset_revision_id,
        locale_id=target.locale_id,
    )
    assert registry.records_for(
        ruleset_id=target.ruleset_id,
        ruleset_revision_id=target.ruleset_revision_id,
        locale_id=target.locale_id,
    ) == (record,)


def test_registry_validator_rejects_duplicate_targets() -> None:
    target = support_target()
    with pytest.raises(SupportRegistryValidationError, match="duplicate support target"):
        validate_support_registry(SupportRegistry(targets=(target, target)))


def test_registry_validator_rejects_orphaned_validation_record() -> None:
    with pytest.raises(SupportRegistryValidationError, match="undeclared target"):
        validate_support_registry(
            SupportRegistry(validation_records=(validation_record(),))
        )
