from __future__ import annotations

import json
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

import yaml

from sentry_copilot.encounter.catalog import EncounterMapCatalog
from sentry_copilot.encounter.confirmed_banned_operators import (
    ConfirmedBannedOperatorCatalog,
    load_default_confirmed_banned_operator_catalog,
    project_confirmed_banned_operator_rows,
    resolve_confirmed_banned_operators,
)
from sentry_copilot.encounter.lifecycle import begin_encounter
from sentry_copilot.encounter.major_covenant_ban_catalog import (
    MajorCovenantPresentationCatalog,
    MajorCovenantPresentationDefinition,
)
from sentry_copilot.encounter.models import (
    MAJOR_COVENANT_IDS,
    CovenantBanState,
    LocalizedText,
    MajorCovenantBanSnapshot,
    MajorCovenantBanStateEntry,
)
from sentry_copilot.encounter.presentation import present_encounter
from sentry_copilot.services.live_encounter_preview import (
    InfoReferenceLoadFailure,
    LiveEncounterPreviewController,
    _sanitize_catalog_load_failure,
)

_YAN = "covenant.covenant_latter.yan"
_DEXTERITY = "covenant.covenant_latter.dexterity"
_VICTORIA = "covenant.covenant_latter.victoria"
_KAZIMIERZ = "covenant.covenant_latter.kazimierz"
_ASSAULT = "covenant.covenant_latter.assault"
_KJERAG = "covenant.covenant_latter.kjerag"
_SWIFTNESS = "covenant.covenant_latter.swiftness"
_SIRACUSA = "covenant.covenant_latter.siracusa"
_SUPPORT_OPERATOR = "covenant.covenant_latter.support_operator"


def _catalog_root() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "catalogs" / "covenant_latter"


def _raw_catalog_semantics() -> tuple[
    dict[str, tuple[int, tuple[str, ...]]],
    dict[str, str],
    tuple[dict[str, object], ...],
    frozenset[str],
]:
    """Calculate expectations directly from public YAML, without production resolver calls."""

    root = _catalog_root()
    operators = yaml.safe_load((root / "operator_catalog.yaml").read_text(encoding="utf-8"))[
        "operators"
    ]
    covenants = yaml.safe_load((root / "covenant_catalog.yaml").read_text(encoding="utf-8"))[
        "covenants"
    ]
    memberships = yaml.safe_load(
        (root / "operator_covenant_memberships.yaml").read_text(encoding="utf-8")
    )["memberships"]
    covenant_names = {item["covenant_id"]: item["name_zh_CN"] for item in covenants}
    static_routes = {
        item["covenant_id"]
        for item in covenants
        if item["membership_mode"] == "explicit"
        and item["query_role"]["counts_as_static_recruitment_route"] is True
    }
    disableable_targets = frozenset(
        item["covenant_id"]
        for item in covenants
        if item["membership_mode"] == "explicit"
        and item["disable_policy"]["can_be_disabled"] is not False
    )
    memberships_by_operator: dict[str, set[str]] = defaultdict(set)
    for edge in memberships:
        if edge["covenant_id"] in static_routes:
            memberships_by_operator[edge["operator_id"]].add(edge["covenant_id"])
    ordinary = {
        item["operator_id"]: (
            item["tier"],
            tuple(sorted(memberships_by_operator[item["operator_id"]])),
        )
        for item in operators
        if item.get("special_entry") is not True
    }
    return ordinary, covenant_names, tuple(covenants), disableable_targets


def _expected_ids(
    known_states: dict[str, CovenantBanState],
    ordinary: dict[str, tuple[int, tuple[str, ...]]],
    disableable_targets: frozenset[str],
) -> tuple[str, ...]:
    return tuple(
        operator_id
        for operator_id, (tier, membership_ids) in sorted(
            ordinary.items(), key=lambda item: (-item[1][0], item[0])
        )
        if membership_ids
        and all(
            covenant_id in disableable_targets
            and known_states.get(covenant_id) is CovenantBanState.DISABLED
            for covenant_id in membership_ids
        )
    )


def _catalog() -> ConfirmedBannedOperatorCatalog:
    return load_default_confirmed_banned_operator_catalog()


def _major_presentation_catalog() -> MajorCovenantPresentationCatalog:
    labels = {
        _YAN: "炎",
        _KAZIMIERZ: "卡西米尔",
        "covenant.covenant_latter.sargon": "萨尔贡",
    }
    return MajorCovenantPresentationCatalog(
        tuple(
            MajorCovenantPresentationDefinition(
                covenant_id=covenant_id,
                names=(
                    LocalizedText(
                        locale_id="zh_CN",
                        text=labels.get(covenant_id, covenant_id),
                    ),
                ),
            )
            for covenant_id in sorted(MAJOR_COVENANT_IDS)
        )
    )


def _complete_major_snapshot() -> MajorCovenantBanSnapshot:
    disabled = set(sorted(MAJOR_COVENANT_IDS)[:3])
    return MajorCovenantBanSnapshot(
        covenant_states=tuple(
            MajorCovenantBanStateEntry(
                covenant_id=covenant_id,
                state=(
                    CovenantBanState.DISABLED
                    if covenant_id in disabled
                    else CovenantBanState.UNRESTRICTED
                ),
            )
            for covenant_id in sorted(MAJOR_COVENANT_IDS)
        )
    )


def _operator_ids(
    states: dict[str, CovenantBanState],
    catalog: ConfirmedBannedOperatorCatalog,
) -> tuple[str, ...]:
    return tuple(item.operator_id for item in resolve_confirmed_banned_operators(states, catalog))


def test_real_catalog_uses_tier_as_book_count_and_sorts_descending() -> None:
    catalog = _catalog()
    resolved = resolve_confirmed_banned_operators({_KAZIMIERZ: CovenantBanState.DISABLED}, catalog)
    mlynar = next(item for item in resolved if item.name_zh_CN == "玛恩纳")
    flametail = next(item for item in resolved if item.name_zh_CN == "焰尾")

    assert mlynar.tier == 5
    assert flametail.tier == 4
    assert resolved.index(mlynar) < resolved.index(flametail)
    assert all(item.tier >= resolved[index + 1].tier for index, item in enumerate(resolved[:-1]))


def test_partial_and_expanded_states_respect_every_static_membership() -> None:
    catalog = _catalog()
    partial = {_YAN: CovenantBanState.DISABLED}
    expanded = {_YAN: CovenantBanState.DISABLED, _DEXTERITY: CovenantBanState.DISABLED}

    partial_ids = _operator_ids(partial, catalog)
    expanded_ids = _operator_ids(expanded, catalog)
    rows = project_confirmed_banned_operator_rows(expanded, catalog)
    yan_row = next(row for row in rows if row.covenant_id == _YAN)
    dexterity_row = next(row for row in rows if row.covenant_id == _DEXTERITY)

    assert "operator.covenant_latter.op_006" in partial_ids  # 惊蛰 / 炎
    assert "operator.covenant_latter.op_007" not in partial_ids  # 小满 / 炎 + 灵巧
    assert "operator.covenant_latter.op_007" in expanded_ids
    assert "operator.covenant_latter.op_007" in {item.operator_id for item in yan_row.operators}
    assert "operator.covenant_latter.op_007" in {
        item.operator_id for item in dexterity_row.operators
    }


def test_real_catalog_examples_do_not_guess_unknown_or_unrestricted_memberships() -> None:
    catalog = _catalog()

    assert "operator.covenant_latter.op_012" in _operator_ids(  # 烛煌 / 炎 + 维多利亚
        {_YAN: CovenantBanState.DISABLED, _VICTORIA: CovenantBanState.DISABLED}, catalog
    )
    assert "operator.covenant_latter.op_089" not in _operator_ids(  # 瑕光 / 卡西米尔 + 突袭
        {_KAZIMIERZ: CovenantBanState.DISABLED}, catalog
    )
    assert "operator.covenant_latter.op_094" not in _operator_ids(  # 耀骑士临光 / 卡西米尔 + 突袭
        {_KAZIMIERZ: CovenantBanState.DISABLED}, catalog
    )
    assert "operator.covenant_latter.op_047" not in _operator_ids(  # 锏 / 谢拉格 + 卡西米尔 + 迅捷
        {
            _KJERAG: CovenantBanState.DISABLED,
            _KAZIMIERZ: CovenantBanState.DISABLED,
        },
        catalog,
    )
    assert "operator.covenant_latter.op_006" not in _operator_ids(
        {_YAN: CovenantBanState.UNRESTRICTED}, catalog
    )
    assert "operator.covenant_latter.special_support" not in {
        item.operator_id
        for item in resolve_confirmed_banned_operators(
            {item.covenant_id: CovenantBanState.DISABLED for item in catalog.covenant_definitions},
            catalog,
        )
    }


def test_suzuran_retains_non_disableable_support_operator_recruitment_route() -> None:
    catalog = _catalog()
    suzuran_id = "operator.covenant_latter.op_081"
    support_operator = catalog.covenant_by_id(_SUPPORT_OPERATOR)

    assert catalog.membership_ids_for(suzuran_id) == tuple(sorted((_SIRACUSA, _SUPPORT_OPERATOR)))
    assert support_operator is not None
    assert support_operator.static_recruitment_route is True
    assert support_operator.disableable_ban_target is False
    assert suzuran_id not in _operator_ids({_SIRACUSA: CovenantBanState.DISABLED}, catalog)

    rows = project_confirmed_banned_operator_rows(
        {_SIRACUSA: CovenantBanState.DISABLED, _SUPPORT_OPERATOR: CovenantBanState.DISABLED},
        catalog,
    )
    assert all(row.covenant_id != _SUPPORT_OPERATOR for row in rows)


def test_rows_are_deterministic_and_have_no_duplicate_operator() -> None:
    catalog = _catalog()
    states = {
        _YAN: CovenantBanState.DISABLED,
        _DEXTERITY: CovenantBanState.DISABLED,
        _VICTORIA: CovenantBanState.DISABLED,
    }
    rows = project_confirmed_banned_operator_rows(states, catalog)

    assert tuple(row.covenant_id for row in rows) == tuple(sorted(row.covenant_id for row in rows))
    for row in rows:
        ids = tuple(item.operator_id for item in row.operators)
        assert len(ids) == len(set(ids))
        assert ids == tuple(
            item.operator_id
            for item in sorted(row.operators, key=lambda item: (-item.tier, item.operator_id))
        )


def test_major_snapshot_presentation_is_partial_and_does_not_change_progress() -> None:
    catalog = _catalog()
    disabled = {_YAN, _KAZIMIERZ, "covenant.covenant_latter.sargon"}
    snapshot = MajorCovenantBanSnapshot(
        covenant_states=tuple(
            MajorCovenantBanStateEntry(
                covenant_id=covenant_id,
                state=(
                    CovenantBanState.DISABLED
                    if covenant_id in disabled
                    else CovenantBanState.UNRESTRICTED
                ),
            )
            for covenant_id in sorted(MAJOR_COVENANT_IDS)
        )
    )
    session = begin_encounter("confirmed-bans.presentation").model_copy(
        update={"major_covenant_ban": snapshot}
    )
    view = present_encounter(
        session,
        EncounterMapCatalog(definitions=()),
        locale_id="zh_CN",
        major_covenant_catalog=_major_presentation_catalog(),
        confirmed_banned_operator_catalog=catalog,
    )

    assert all(name in view.items[3].value for name in ("萨尔贡", "炎", "卡西米尔"))
    assert "玛恩纳" not in view.items[3].value
    assert "已确认禁用干员" not in view.items[3].value
    assert view.confirmed_banned_operator_rows
    kazimierz = next(
        row for row in view.confirmed_banned_operator_rows if row.display_name == "卡西米尔"
    )
    assert kazimierz.operators[0].operator_id == "operator.covenant_latter.op_093"
    assert kazimierz.operators[0].display_name == "玛恩纳"
    assert kazimierz.operators[0].tier == 5
    assert kazimierz.operators[0].portrait_key == "prts:玛恩纳"
    assert tuple(card.tier for card in kazimierz.operators) == tuple(
        sorted((card.tier for card in kazimierz.operators), reverse=True)
    )
    assert session.ordinary_progress_count == 0


def test_presentation_does_not_show_confirmed_rows_without_a_major_snapshot() -> None:
    view = present_encounter(
        begin_encounter("confirmed-bans.no-snapshot"),
        EncounterMapCatalog(definitions=()),
        locale_id="zh_CN",
        confirmed_banned_operator_catalog=_catalog(),
    )

    assert view.confirmed_banned_operator_rows == ()


def test_presentation_keeps_multi_membership_cards_in_each_confirmed_covenant_row() -> None:
    catalog = _catalog()
    disabled = {_YAN, _KJERAG, _VICTORIA}
    session = begin_encounter("confirmed-bans.multi-membership").model_copy(
        update={
            "major_covenant_ban": MajorCovenantBanSnapshot(
                covenant_states=tuple(
                    MajorCovenantBanStateEntry(
                        covenant_id=covenant_id,
                        state=(
                            CovenantBanState.DISABLED
                            if covenant_id in disabled
                            else CovenantBanState.UNRESTRICTED
                        ),
                    )
                    for covenant_id in sorted(MAJOR_COVENANT_IDS)
                )
            )
        }
    )

    view = present_encounter(
        session,
        EncounterMapCatalog(definitions=()),
        locale_id="zh_CN",
        confirmed_banned_operator_catalog=catalog,
    )
    rows_by_id = {row.covenant_id: row for row in view.confirmed_banned_operator_rows}

    assert "operator.covenant_latter.op_030" in {
        card.operator_id for card in rows_by_id[_VICTORIA].operators
    }
    assert "operator.covenant_latter.op_030" in {
        card.operator_id for card in rows_by_id[_KJERAG].operators
    }


def test_presentation_with_unavailable_operator_catalog_has_no_detail_rows() -> None:
    session = begin_encounter("confirmed-bans.unavailable").model_copy(
        update={"major_covenant_ban": _complete_major_snapshot()}
    )

    view = present_encounter(session, EncounterMapCatalog(definitions=()), locale_id="zh_CN")

    assert view.confirmed_banned_operator_rows == ()


def test_all_56_major_disabled_combinations_match_independent_raw_catalog_expectations() -> None:
    catalog = _catalog()
    major_ids = tuple(sorted(MAJOR_COVENANT_IDS))
    ordinary, _, _, disableable_targets = _raw_catalog_semantics()

    for disabled_ids in combinations(major_ids, 3):
        states = {
            covenant_id: (
                CovenantBanState.DISABLED
                if covenant_id in disabled_ids
                else CovenantBanState.UNRESTRICTED
            )
            for covenant_id in major_ids
        }
        resolved = resolve_confirmed_banned_operators(states, catalog)
        rows = project_confirmed_banned_operator_rows(states, catalog)
        actual_ids = tuple(item.operator_id for item in resolved)

        assert actual_ids == _expected_ids(states, ordinary, disableable_targets)
        assert len(actual_ids) == len(set(actual_ids))
        assert all(
            item.operator_id != "operator.covenant_latter.special_support" for item in resolved
        )
        assert all(
            all(
                states.get(covenant_id) is CovenantBanState.DISABLED
                for covenant_id in item.membership_ids
            )
            for item in resolved
        )
        for row in rows:
            row_ids = tuple(item.operator_id for item in row.operators)
            assert row_ids == tuple(dict.fromkeys(row_ids))
            assert all(row.covenant_id in ordinary[item.operator_id][1] for item in row.operators)
            assert row_ids == tuple(
                item.operator_id
                for item in sorted(row.operators, key=lambda item: (-item.tier, item.operator_id))
            )


def test_every_ordinary_operator_requires_every_membership_and_projects_only_to_it() -> None:
    catalog = _catalog()
    ordinary, _, _, disableable_targets = _raw_catalog_semantics()
    all_disabled = {
        covenant_id: CovenantBanState.DISABLED
        for _, membership_ids in ordinary.values()
        for covenant_id in membership_ids
        if covenant_id in disableable_targets
    }
    confirmed = resolve_confirmed_banned_operators(all_disabled, catalog)
    rows = project_confirmed_banned_operator_rows(all_disabled, catalog)
    by_row = {row.covenant_id: {item.operator_id for item in row.operators} for row in rows}
    ban_eligible = set(_expected_ids(all_disabled, ordinary, disableable_targets))

    assert {item.operator_id for item in confirmed} == ban_eligible
    for operator_id, (_, membership_ids) in ordinary.items():
        if not membership_ids or not set(membership_ids) <= disableable_targets:
            assert operator_id not in {item.operator_id for item in confirmed}
            continue
        assert all(operator_id in by_row[covenant_id] for covenant_id in membership_ids)
        assert all(
            operator_id not in row_ids
            for covenant_id, row_ids in by_row.items()
            if covenant_id not in membership_ids
        )
        for covenant_id in membership_ids:
            unknown = dict(all_disabled)
            unknown.pop(covenant_id)
            unrestricted = dict(all_disabled)
            unrestricted[covenant_id] = CovenantBanState.UNRESTRICTED
            assert operator_id not in _operator_ids(unknown, catalog)
            assert operator_id not in _operator_ids(unrestricted, catalog)


def test_public_catalog_integrity_and_ban_relevance_metadata() -> None:
    root = _catalog_root()
    operators = yaml.safe_load((root / "operator_catalog.yaml").read_text(encoding="utf-8"))[
        "operators"
    ]
    covenants = yaml.safe_load((root / "covenant_catalog.yaml").read_text(encoding="utf-8"))[
        "covenants"
    ]
    memberships = yaml.safe_load(
        (root / "operator_covenant_memberships.yaml").read_text(encoding="utf-8")
    )["memberships"]
    special_rules = yaml.safe_load(
        (root / "covenant_special_rules.yaml").read_text(encoding="utf-8")
    )
    ordinary, _, _, _ = _raw_catalog_semantics()
    operator_ids = {item["operator_id"] for item in operators}
    covenant_ids = {item["covenant_id"] for item in covenants}
    edge_ids = {(edge["operator_id"], edge["covenant_id"]) for edge in memberships}
    tiers = Counter(item["tier"] for item in operators if item.get("special_entry") is not True)

    assert len(operators) == 113
    assert len(ordinary) == 112
    assert sum(item.get("special_entry") is True for item in operators) == 1
    assert set(tiers) == {1, 2, 3, 4, 5, 6}
    assert tiers == Counter({1: 16, 2: 17, 3: 19, 4: 22, 5: 19, 6: 19})
    assert all(
        isinstance(item["tier"], int) for item in operators if item.get("special_entry") is not True
    )
    assert len(memberships) == 191
    assert len(edge_ids) == len(memberships)
    assert all(edge["operator_id"] in operator_ids for edge in memberships)
    assert all(edge["covenant_id"] in covenant_ids for edge in memberships)
    assert all(
        any(edge["operator_id"] == operator_id for edge in memberships) for operator_id in ordinary
    )
    assert all(
        isinstance(item["membership_mode"], str)
        and isinstance(item["query_role"]["counts_as_static_recruitment_route"], bool)
        and (
            item["disable_policy"]["can_be_disabled"] is None
            or isinstance(item["disable_policy"]["can_be_disabled"], bool)
        )
        for item in covenants
    )
    ultimate = next(
        item for item in covenants if item["covenant_id"].endswith("ultimate_technique")
    )
    support_operator = next(
        item for item in covenants if item["covenant_id"].endswith("support_operator")
    )
    assert ultimate["membership_mode"] == "rule_based_elite_state"
    assert all(edge["covenant_id"] != ultimate["covenant_id"] for edge in memberships)
    assert support_operator["disable_policy"]["can_be_disabled"] is False
    resolved_support_operator = _catalog().covenant_by_id(support_operator["covenant_id"])
    assert resolved_support_operator is not None
    assert resolved_support_operator.static_recruitment_route is True
    assert resolved_support_operator.disableable_ban_target is False
    assert any(item["kind"] == "ultimate_technique" for item in special_rules["dynamic_rules"])


def test_catalog_diagnostics_are_derived_and_failures_are_path_safe() -> None:
    catalog = _catalog()
    disabled = {_YAN, _KAZIMIERZ, "covenant.covenant_latter.sargon"}
    session = begin_encounter("confirmed-bans.diagnostics").model_copy(
        update={
            "major_covenant_ban": MajorCovenantBanSnapshot(
                covenant_states=tuple(
                    MajorCovenantBanStateEntry(
                        covenant_id=covenant_id,
                        state=(
                            CovenantBanState.DISABLED
                            if covenant_id in disabled
                            else CovenantBanState.UNRESTRICTED
                        ),
                    )
                    for covenant_id in sorted(MAJOR_COVENANT_IDS)
                )
            )
        }
    )
    controller = LiveEncounterPreviewController(confirmed_banned_operator_catalog=catalog)
    controller._session = session  # noqa: SLF001 - exercise the diagnostic-only projection seam.
    diagnostic = json.loads(controller.diagnostic_json())
    missing = _sanitize_catalog_load_failure(
        FileNotFoundError(2, "not found", r"C:\private\catalog\operator_catalog.yaml")
    )

    assert diagnostic["confirmed_banned_operator_catalog_status"] == "available"
    assert diagnostic["confirmed_banned_operator_catalog_error"] is None
    assert diagnostic["confirmed_banned_operator_count"] > 0
    assert diagnostic["confirmed_banned_operator_rows"]
    assert missing == InfoReferenceLoadFailure(
        category="missing_file", reason="required catalog unavailable: operator_catalog.yaml"
    )
