from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml

from sentry_copilot.cli import build_parser
from sentry_copilot.vision.visual_references import (
    VisualCatalogKind,
    VisualCatalogValidationError,
    VisualMatchStatus,
    load_visual_reference_catalog,
    match_visual_catalog,
    write_visual_match_report,
)


def _pattern(seed: int) -> np.ndarray[tuple[int, int, int], np.dtype[np.uint8]]:
    values = np.arange(60, dtype=np.uint8).reshape(4, 5, 3)
    return (values + seed).astype(np.uint8)


def _write_image(path: Path, image: np.ndarray[tuple[int, int, int], np.dtype[np.uint8]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    assert cv2.imwrite(str(path), image)


def _write_catalog(
    root: Path,
    *,
    kind: str,
    assets: list[dict[str, str]],
    references: list[dict[str, str]],
) -> Path:
    document: dict[str, object] = {
        "schema_version": 1,
        "kind": kind,
        "assets": assets,
        "strategy_references": references if kind == "strategy" else [],
        "avatar_references": references if kind == "avatar" else [],
    }
    path = root / "catalog.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def _asset(root: Path, asset_id: str, relative_path: str, image: np.ndarray) -> dict[str, str]:
    path = root / relative_path
    _write_image(path, image)
    return {
        "asset_id": asset_id,
        "asset_reference": relative_path,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "provenance": "synthetic-generated",
    }


def _query(root: Path, template: np.ndarray) -> Path:
    query = np.zeros((12, 16, 3), dtype=np.uint8)
    query[3:7, 6:11] = template
    path = root / "query.png"
    _write_image(path, query)
    return path


def test_successful_strategy_match_and_report_use_only_explicit_synthetic_assets(
    tmp_path: Path,
) -> None:
    matching = _pattern(10)
    catalog_path = _write_catalog(
        tmp_path,
        kind="strategy",
        assets=[
            _asset(tmp_path, "asset.synthetic.strategy-a", "assets/a.png", matching),
            _asset(
                tmp_path,
                "asset.synthetic.strategy-b",
                "assets/b.png",
                np.flip(_pattern(80), axis=1).copy(),
            ),
        ],
        references=[
            {
                "strategy_id": "strategy.synthetic.a",
                "asset_id": "asset.synthetic.strategy-a",
                "ruleset_revision_id": "revision.synthetic.one",
                "reference_kind": "selection_render",
            },
            {
                "strategy_id": "strategy.synthetic.b",
                "asset_id": "asset.synthetic.strategy-b",
            },
        ],
    )

    catalog = load_visual_reference_catalog(catalog_path)
    result = match_visual_catalog(
        catalog=catalog,
        query_path=_query(tmp_path, matching),
        minimum_score=0.99,
    )
    report_path = write_visual_match_report(result, tmp_path / "output")

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert catalog.kind is VisualCatalogKind.STRATEGY
    assert result.status is VisualMatchStatus.MATCHED
    assert result.selected_candidate is not None
    assert result.selected_candidate.identity_id == "strategy.synthetic.a"
    assert result.selected_candidate.asset_id == "asset.synthetic.strategy-a"
    assert payload["status"] == "matched"
    assert payload["catalog_schema_version"] == 1
    assert payload["catalog_fingerprint"] == catalog.fingerprint
    assert len(catalog.fingerprint) == 64
    assert payload["query"]["width"] == 16
    assert len(payload["candidates"]) == 2


def test_avatar_catalog_allows_multiple_references_for_one_nonunique_avatar(tmp_path: Path) -> None:
    matching = _pattern(20)
    catalog_path = _write_catalog(
        tmp_path,
        kind="avatar",
        assets=[
            _asset(
                tmp_path, "asset.synthetic.avatar-canonical", "assets/canonical.png", _pattern(1)
            ),
            _asset(tmp_path, "asset.synthetic.avatar-battle", "assets/battle.png", matching),
        ],
        references=[
            {
                "avatar_id": "avatar.synthetic.shared",
                "asset_id": "asset.synthetic.avatar-canonical",
            },
            {"avatar_id": "avatar.synthetic.shared", "asset_id": "asset.synthetic.avatar-battle"},
        ],
    )

    catalog = load_visual_reference_catalog(catalog_path)
    result = match_visual_catalog(catalog=catalog, query_path=_query(tmp_path, matching))

    assert catalog.kind is VisualCatalogKind.AVATAR
    assert len(catalog.references) == 2
    assert result.status is VisualMatchStatus.MATCHED
    assert result.selected_candidate is not None
    assert result.selected_candidate.identity_id == "avatar.synthetic.shared"


def test_below_threshold_is_unresolved_and_identical_different_identities_are_ambiguous(
    tmp_path: Path,
) -> None:
    matching = _pattern(30)
    assets = [
        _asset(tmp_path, "asset.synthetic.first", "assets/first.png", matching),
        _asset(tmp_path, "asset.synthetic.second", "assets/second.png", matching),
    ]
    catalog_path = _write_catalog(
        tmp_path,
        kind="strategy",
        assets=assets,
        references=[
            {"strategy_id": "strategy.synthetic.first", "asset_id": "asset.synthetic.first"},
            {"strategy_id": "strategy.synthetic.second", "asset_id": "asset.synthetic.second"},
        ],
    )
    catalog = load_visual_reference_catalog(catalog_path)

    ambiguous = match_visual_catalog(
        catalog=catalog,
        query_path=_query(tmp_path, matching),
        minimum_score=0.99,
        ambiguity_margin=0.02,
    )
    unmatched_query = np.zeros((12, 16, 3), dtype=np.uint8)
    unmatched_path = tmp_path / "unmatched.png"
    _write_image(unmatched_path, unmatched_query)
    unresolved = match_visual_catalog(
        catalog=catalog,
        query_path=unmatched_path,
        minimum_score=0.99,
    )

    assert ambiguous.status is VisualMatchStatus.AMBIGUOUS
    assert ambiguous.selected_candidate is None
    assert unresolved.status is VisualMatchStatus.UNRESOLVED
    assert unresolved.selected_candidate is None


@pytest.mark.parametrize("problem", ["duplicate", "bad_hash", "missing", "invalid"])
def test_catalog_rejects_invalid_or_undeclared_synthetic_assets(
    tmp_path: Path, problem: str
) -> None:
    image = _pattern(40)
    asset = _asset(tmp_path, "asset.synthetic.one", "assets/one.png", image)
    if problem == "duplicate":
        assets = [asset, {**asset, "asset_reference": "assets/one.png"}]
    elif problem == "bad_hash":
        assets = [{**asset, "sha256": "0" * 64}]
    elif problem == "missing":
        assets = [{**asset, "asset_reference": "assets/missing.png"}]
    else:
        bad = tmp_path / "assets" / "bad.png"
        bad.write_bytes(b"not a synthetic image")
        assets = [{**asset, "asset_reference": "assets/bad.png"}]
    catalog_path = _write_catalog(
        tmp_path,
        kind="avatar",
        assets=assets,
        references=[{"avatar_id": "avatar.synthetic.one", "asset_id": "asset.synthetic.one"}],
    )

    with pytest.raises(VisualCatalogValidationError):
        load_visual_reference_catalog(catalog_path)


def test_cli_accepts_only_explicit_catalog_query_and_output_paths() -> None:
    args = build_parser().parse_args(
        [
            "visual-catalog-match",
            "--kind",
            "strategy",
            "--catalog",
            "synthetic-catalog.yaml",
            "--image",
            "synthetic-query.png",
            "--output",
            "synthetic-output",
            "--minimum-score",
            "0.91",
            "--ambiguity-margin",
            "0.03",
        ]
    )

    assert args.command == "visual-catalog-match"
    assert args.kind == "strategy"
    assert args.catalog == Path("synthetic-catalog.yaml")
    assert args.image == Path("synthetic-query.png")
