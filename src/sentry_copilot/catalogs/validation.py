from __future__ import annotations

from collections import Counter
from collections.abc import Hashable, Iterable
from pathlib import Path, PurePosixPath, PureWindowsPath

from sentry_copilot.domain.strategy import (
    StrategyAvailability,
    StrategyCatalog,
)
from sentry_copilot.domain.support import SupportRegistry


class CatalogValidationError(ValueError):
    """Raised when a catalog violates cross-record or asset invariants."""

    def __init__(self, issues: Iterable[str]) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(self.issues))


class SupportRegistryValidationError(ValueError):
    """Raised when support metadata contains duplicate or orphaned records."""

    def __init__(self, issues: Iterable[str]) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(self.issues))


def validate_catalog(catalog: StrategyCatalog, *, asset_root: Path) -> None:
    """Validate catalog relationships and resolve every referenced icon asset."""

    issues: list[str] = []
    rulesets = {ruleset.ruleset_id: ruleset for ruleset in catalog.rulesets}
    revisions = {
        revision.ruleset_revision_id: revision for revision in catalog.revisions
    }
    strategy_ids = {
        identity.strategy_id for identity in catalog.strategy_identities
    }

    issues.extend(
        _duplicates_as_issues(
            (ruleset.ruleset_id for ruleset in catalog.rulesets),
            "ruleset_id",
        )
    )
    issues.extend(
        _duplicates_as_issues(
            (
                revision.ruleset_revision_id
                for revision in catalog.revisions
            ),
            "ruleset_revision_id",
        )
    )
    issues.extend(
        _duplicates_as_issues(
            (identity.strategy_id for identity in catalog.strategy_identities),
            "strategy_id",
        )
    )

    revision_orders = (
        (revision.ruleset_id, revision.revision_order)
        for revision in catalog.revisions
    )
    issues.extend(_duplicates_as_issues(revision_orders, "revision_order"))

    for ruleset in catalog.rulesets:
        actual_revision_ids = frozenset(
            revision.ruleset_revision_id
            for revision in catalog.revisions
            if revision.ruleset_id == ruleset.ruleset_id
        )
        if actual_revision_ids != ruleset.revision_ids:
            issues.append(
                f"ruleset {ruleset.ruleset_id} revision_ids do not match revision records"
            )

    for revision in catalog.revisions:
        owning_ruleset = rulesets.get(revision.ruleset_id)
        if owning_ruleset is None:
            issues.append(
                f"revision {revision.ruleset_revision_id} references unknown ruleset "
                f"{revision.ruleset_id}"
            )
        elif revision.ruleset_revision_id not in owning_ruleset.revision_ids:
            issues.append(
                f"revision {revision.ruleset_revision_id} is not declared by its ruleset"
            )

    profile_keys = [
        (profile.ruleset_revision_id, profile.strategy_id)
        for profile in catalog.profiles
    ]
    issues.extend(_duplicates_as_issues(profile_keys, "strategy profile"))
    profile_key_set = set(profile_keys)

    for profile in catalog.profiles:
        if profile.ruleset_revision_id not in revisions:
            issues.append(
                f"profile {profile.strategy_id} references unknown revision "
                f"{profile.ruleset_revision_id}"
            )
        if profile.strategy_id not in strategy_ids:
            issues.append(
                f"profile references unknown strategy identity {profile.strategy_id}"
            )
        issues.extend(
            _validate_asset_reference(
                profile.icon_asset_reference,
                asset_root=asset_root,
                strategy_id=profile.strategy_id,
                revision_id=profile.ruleset_revision_id,
            )
        )

    locale_keys = [
        (
            resource.ruleset_revision_id,
            resource.strategy_id,
            resource.locale_id,
        )
        for resource in catalog.locale_resources
    ]
    issues.extend(_duplicates_as_issues(locale_keys, "locale resource"))
    locale_key_set = set(locale_keys)

    for resource in catalog.locale_resources:
        profile_key = (resource.ruleset_revision_id, resource.strategy_id)
        if profile_key not in profile_key_set:
            issues.append(
                "locale resource references a strategy without a profile in the same "
                f"revision: {profile_key}"
            )
            continue
        resource_revision = revisions.get(resource.ruleset_revision_id)
        if resource_revision is None:
            continue
        resource_ruleset = rulesets.get(resource_revision.ruleset_id)
        if (
            resource_ruleset is not None
            and resource.locale_id not in resource_ruleset.supported_locales
        ):
            issues.append(
                "locale resource uses a locale not declared by its ruleset: "
                f"{resource.ruleset_revision_id}/{resource.strategy_id}/"
                f"{resource.locale_id}"
            )

    for profile in catalog.profiles:
        if profile.availability != StrategyAvailability.AVAILABLE:
            continue
        profile_revision = revisions.get(profile.ruleset_revision_id)
        if profile_revision is None:
            continue
        profile_ruleset = rulesets.get(profile_revision.ruleset_id)
        if profile_ruleset is None:
            continue
        for locale_id in profile_ruleset.supported_locales:
            locale_key = (
                profile.ruleset_revision_id,
                profile.strategy_id,
                locale_id,
            )
            if locale_key not in locale_key_set:
                issues.append(
                    "available strategy is missing locale resource for "
                    f"{profile.ruleset_revision_id}/{profile.strategy_id}/{locale_id}"
                )

    if issues:
        raise CatalogValidationError(issues)


def validate_support_registry(registry: SupportRegistry) -> None:
    """Validate support targets without promoting any target to validated support."""

    issues: list[str] = []
    target_keys = [
        (target.ruleset_id, target.ruleset_revision_id, target.locale_id)
        for target in registry.targets
    ]
    issues.extend(_duplicates_as_issues(target_keys, "support target"))
    target_key_set = set(target_keys)

    for record in registry.validation_records:
        record_key = (
            record.ruleset_id,
            record.ruleset_revision_id,
            record.locale_id,
        )
        if record_key not in target_key_set:
            issues.append(f"validation record references undeclared target {record_key}")

    if issues:
        raise SupportRegistryValidationError(issues)


def _validate_asset_reference(
    reference: str,
    *,
    asset_root: Path,
    strategy_id: str,
    revision_id: str,
) -> list[str]:
    label = f"{revision_id}/{strategy_id}"
    posix_path = PurePosixPath(reference)
    windows_path = PureWindowsPath(reference)
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or ".." in posix_path.parts
        or "\\" in reference
    ):
        return [f"icon asset reference for {label} must be a safe relative path"]

    resolved_root = asset_root.resolve()
    resolved_asset = asset_root.joinpath(*posix_path.parts).resolve()
    if not resolved_asset.is_relative_to(resolved_root):
        return [f"icon asset reference for {label} escapes the catalog root"]
    if not resolved_asset.is_file():
        return [f"icon asset reference for {label} does not resolve to a file"]
    return []


def _duplicates_as_issues(values: Iterable[Hashable], label: str) -> list[str]:
    counts = Counter(values)
    duplicates = [value for value, count in counts.items() if count > 1]
    return [f"duplicate {label}: {value}" for value in duplicates]
