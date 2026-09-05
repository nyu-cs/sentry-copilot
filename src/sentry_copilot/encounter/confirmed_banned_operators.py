"""Pure confirmed-banned-operator derivation from declared Covenant catalogs.

The resolver deliberately knows nothing about visual recognition or encounter lifecycle.  A
membership is only enough to confirm a Ban when every static recruitment route of the operator
is known and disabled for the current encounter.  A route can be a valid source of an operator
without itself being a disableable Ban target.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import yaml

from .models import CovenantBanState


@dataclass(frozen=True)
class BannedOperatorDefinition:
    """One ordinary fixed-roster operator eligible for confirmed-Ban derivation."""

    operator_id: str
    name_zh_CN: str
    tier: int


@dataclass(frozen=True)
class CovenantDefinition:
    """One catalog Covenant's recruitment-route and Ban-target semantics."""

    covenant_id: str
    name_zh_CN: str
    static_recruitment_route: bool
    disableable_ban_target: bool


@dataclass(frozen=True)
class ConfirmedBannedOperatorCatalog:
    """Validated public operator/Covenant data, with no runtime-state authority."""

    operators: tuple[BannedOperatorDefinition, ...]
    covenant_definitions: tuple[CovenantDefinition, ...]
    membership_ids_by_operator: tuple[tuple[str, tuple[str, ...]], ...]

    def __post_init__(self) -> None:
        operator_ids = tuple(item.operator_id for item in self.operators)
        covenant_ids = tuple(item.covenant_id for item in self.covenant_definitions)
        membership_operator_ids = tuple(item[0] for item in self.membership_ids_by_operator)
        if len(operator_ids) != len(set(operator_ids)):
            raise ValueError("confirmed-Ban operator catalog has duplicate operator IDs")
        if len(covenant_ids) != len(set(covenant_ids)):
            raise ValueError("confirmed-Ban operator catalog has duplicate Covenant IDs")
        if len(membership_operator_ids) != len(set(membership_operator_ids)):
            raise ValueError("confirmed-Ban operator catalog has duplicate membership owners")
        if not set(membership_operator_ids) <= set(operator_ids):
            raise ValueError("confirmed-Ban memberships reference an unknown operator")
        for _, membership_ids in self.membership_ids_by_operator:
            if len(membership_ids) != len(set(membership_ids)):
                raise ValueError("confirmed-Ban memberships must be unique per operator")
            if not set(membership_ids) <= set(covenant_ids):
                raise ValueError("confirmed-Ban memberships reference an unknown Covenant")

    def covenant_by_id(self, covenant_id: str) -> CovenantDefinition | None:
        return next(
            (item for item in self.covenant_definitions if item.covenant_id == covenant_id), None
        )

    def membership_ids_for(self, operator_id: str) -> tuple[str, ...]:
        return next(
            (
                membership_ids
                for item_id, membership_ids in self.membership_ids_by_operator
                if item_id == operator_id
            ),
            (),
        )


@dataclass(frozen=True)
class ConfirmedBannedOperator:
    """An operator whose complete static Ban-relevant membership set is disabled."""

    operator_id: str
    name_zh_CN: str
    tier: int
    membership_ids: tuple[str, ...]


@dataclass(frozen=True)
class ConfirmedBannedOperatorRow:
    """One disabled-Covenant presentation row; entries may intentionally repeat across rows."""

    covenant_id: str
    covenant_name_zh_CN: str
    operators: tuple[ConfirmedBannedOperator, ...]


def load_default_confirmed_banned_operator_catalog() -> ConfirmedBannedOperatorCatalog:
    """Load only the three declared public Covenant/operator catalogs; never discover assets."""

    repository_root = Path(__file__).resolve().parents[3]
    catalog_root = repository_root / "data" / "catalogs" / "covenant_latter"
    return load_confirmed_banned_operator_catalog(
        operator_catalog_path=catalog_root / "operator_catalog.yaml",
        membership_catalog_path=catalog_root / "operator_covenant_memberships.yaml",
        covenant_catalog_path=catalog_root / "covenant_catalog.yaml",
        special_rules_path=catalog_root / "covenant_special_rules.yaml",
    )


def load_confirmed_banned_operator_catalog(
    *,
    operator_catalog_path: Path,
    membership_catalog_path: Path,
    covenant_catalog_path: Path,
    special_rules_path: Path,
) -> ConfirmedBannedOperatorCatalog:
    """Load and cross-validate declared public data for the pure confirmed-Ban query."""

    operators_raw = _required_records(_load_yaml_mapping(operator_catalog_path), "operators")
    memberships_raw = _required_records(
        _load_yaml_mapping(membership_catalog_path), "memberships"
    )
    covenants_raw = _required_records(_load_yaml_mapping(covenant_catalog_path), "covenants")
    _validate_special_rules(_load_yaml_mapping(special_rules_path))

    covenants = tuple(_covenant_from_record(record) for record in covenants_raw)
    covenant_by_id = {item.covenant_id: item for item in covenants}
    if len(covenant_by_id) != len(covenants):
        raise ValueError("Covenant catalog has duplicate Covenant IDs")

    operators = tuple(
        operator
        for record in operators_raw
        if (operator := _ordinary_operator_from_record(record)) is not None
    )
    operator_by_id = {item.operator_id: item for item in operators}
    if len(operator_by_id) != len(operators):
        raise ValueError("operator catalog has duplicate ordinary operator IDs")
    all_operator_ids = tuple(_required_text(record, "operator_id") for record in operators_raw)
    if len(all_operator_ids) != len(set(all_operator_ids)):
        raise ValueError("operator catalog has duplicate operator IDs")

    memberships_by_operator: dict[str, set[str]] = defaultdict(set)
    for record in memberships_raw:
        operator_id = _required_text(record, "operator_id")
        covenant_id = _required_text(record, "covenant_id")
        if operator_id not in all_operator_ids:
            raise ValueError("operator membership references an unknown operator")
        if operator_id not in operator_by_id:
            # The only current non-roster special entry is deliberately excluded from normal rows.
            continue
        covenant = covenant_by_id.get(covenant_id)
        if covenant is None:
            raise ValueError("operator membership references an unknown Covenant")
        if covenant.static_recruitment_route:
            memberships_by_operator[operator_id].add(covenant_id)

    return ConfirmedBannedOperatorCatalog(
        operators=operators,
        covenant_definitions=covenants,
        membership_ids_by_operator=tuple(
            (operator.operator_id, tuple(sorted(memberships_by_operator[operator.operator_id])))
            for operator in sorted(operators, key=lambda item: item.operator_id)
        ),
    )


def resolve_confirmed_banned_operators(
    known_covenant_states: Mapping[str, CovenantBanState],
    catalog: ConfirmedBannedOperatorCatalog,
) -> tuple[ConfirmedBannedOperator, ...]:
    """Return operators only when every static recruitment route is known disabled.

    A non-disableable static route (for example ``support_operator``) remains an
    acquisition route, so it deliberately blocks a confirmed-Ban conclusion.
    """

    confirmed = tuple(
        ConfirmedBannedOperator(
            operator_id=operator.operator_id,
            name_zh_CN=operator.name_zh_CN,
            tier=operator.tier,
            membership_ids=membership_ids,
        )
        for operator in catalog.operators
        for membership_ids in (catalog.membership_ids_for(operator.operator_id),)
        if membership_ids
        and all(
            (covenant := catalog.covenant_by_id(covenant_id)) is not None
            and covenant.disableable_ban_target
            and known_covenant_states.get(covenant_id) is CovenantBanState.DISABLED
            for covenant_id in membership_ids
        )
    )
    return tuple(sorted(confirmed, key=lambda item: (-item.tier, item.operator_id)))


def project_confirmed_banned_operator_rows(
    known_covenant_states: Mapping[str, CovenantBanState],
    catalog: ConfirmedBannedOperatorCatalog,
) -> tuple[ConfirmedBannedOperatorRow, ...]:
    """Project confirmed operators into every disabled Covenant row they statically belong to."""

    confirmed = resolve_confirmed_banned_operators(known_covenant_states, catalog)
    rows = tuple(
        ConfirmedBannedOperatorRow(
            covenant_id=covenant_id,
            covenant_name_zh_CN=covenant.name_zh_CN,
            operators=tuple(
                operator for operator in confirmed if covenant_id in operator.membership_ids
            ),
        )
        for covenant_id, covenant in sorted(
            (
                (item.covenant_id, item)
                for item in catalog.covenant_definitions
                if item.disableable_ban_target
                and known_covenant_states.get(item.covenant_id) is CovenantBanState.DISABLED
            ),
            key=lambda item: item[0],
        )
        if any(covenant_id in operator.membership_ids for operator in confirmed)
    )
    return rows


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ValueError("confirmed-Ban catalog YAML is invalid") from error
    if not isinstance(value, dict):
        raise ValueError("confirmed-Ban catalog must contain a mapping")
    return cast(dict[str, Any], value)


def _required_records(value: dict[str, Any], key: str) -> tuple[dict[str, Any], ...]:
    records = value.get(key)
    if not isinstance(records, list) or not all(isinstance(record, dict) for record in records):
        raise ValueError("confirmed-Ban catalog is missing required records")
    return tuple(cast(dict[str, Any], record) for record in records)


def _ordinary_operator_from_record(record: dict[str, Any]) -> BannedOperatorDefinition | None:
    if record.get("special_entry") is True:
        return None
    tier = record.get("tier")
    if not isinstance(tier, int) or isinstance(tier, bool):
        raise ValueError("ordinary operator must have an integer tier")
    if tier < 1:
        raise ValueError("ordinary operator tier must be positive")
    return BannedOperatorDefinition(
        operator_id=_required_text(record, "operator_id"),
        name_zh_CN=_required_text(record, "name_zh_CN"),
        tier=tier,
    )


def _covenant_from_record(record: dict[str, Any]) -> CovenantDefinition:
    membership_mode = _required_text(record, "membership_mode")
    query_role = record.get("query_role")
    disable_policy = record.get("disable_policy")
    if not isinstance(query_role, dict) or not isinstance(disable_policy, dict):
        raise ValueError("Covenant catalog is missing Ban-relevance metadata")
    return CovenantDefinition(
        covenant_id=_required_text(record, "covenant_id"),
        name_zh_CN=_required_text(record, "name_zh_CN"),
        static_recruitment_route=(
            membership_mode == "explicit"
            and query_role.get("counts_as_static_recruitment_route") is True
        ),
        disableable_ban_target=(
            membership_mode == "explicit" and disable_policy.get("can_be_disabled") is not False
        ),
    )


def _validate_special_rules(value: dict[str, Any]) -> None:
    """Ensure the declared dynamic Ultimate rule remains separate from static memberships."""

    rules = value.get("dynamic_rules")
    if not isinstance(rules, list) or not any(
        isinstance(rule, dict) and rule.get("kind") == "ultimate_technique" for rule in rules
    ):
        raise ValueError("special rules are missing the dynamic ultimate-technique declaration")


def _required_text(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("confirmed-Ban catalog record is missing required metadata")
    return value
