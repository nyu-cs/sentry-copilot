from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml

from sentry_copilot.cli import build_parser
from sentry_copilot.image_io import write_bgr_png
from sentry_copilot.vision.local_feature_matching import (
    LocalFeatureMatcherConfig,
    LocalFeatureRejectionReason,
    LocalFeatureVisualMatcher,
    write_local_feature_match_report,
)
from sentry_copilot.vision.visual_references import (
    VisualMatchStatus,
    load_visual_reference_catalog,
)


def _textured_image(seed: int, *, width: int = 88, height: int = 70) -> np.ndarray:
    rng = np.random.default_rng(seed)
    image = rng.integers(20, 90, size=(height, width, 3), dtype=np.uint8)
    cv2.circle(image, (22, 20), 12, (235, 80, 30), 2, cv2.LINE_AA)
    cv2.rectangle(image, (42, 9), (78, 32), (40, 220, 170), 2)
    cv2.line(image, (8, 59), (81, 41), (240, 230, 50), 2, cv2.LINE_AA)
    cv2.putText(image, f"S{seed}", (30, 62), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (250, 250, 250), 2)
    return image


def _unrelated_image() -> np.ndarray:
    image = np.zeros((70, 88, 3), dtype=np.uint8)
    cv2.ellipse(image, (44, 35), (30, 15), 35, 0, 360, (10, 180, 245), 3)
    cv2.line(image, (5, 8), (20, 65), (230, 20, 190), 4, cv2.LINE_AA)
    return image


def _transformed_reference(
    query: np.ndarray,
    *,
    scale: float = 1.35,
    rotation_degrees: float = 0.0,
    x_translation: float = 24.0,
    y_translation: float = 18.0,
) -> np.ndarray:
    radians = math.radians(rotation_degrees)
    cosine = scale * math.cos(radians)
    sine = scale * math.sin(radians)
    transform = np.array(
        [[cosine, -sine, x_translation], [sine, cosine, y_translation]],
        dtype=np.float32,
    )
    return cv2.warpAffine(query, transform, (190, 160), flags=cv2.INTER_CUBIC)


def _write_catalog(
    root: Path,
    entries: list[tuple[str, str, np.ndarray, str]],
    *,
    kind: str = "strategy",
) -> Path:
    assets: list[dict[str, str]] = []
    references: list[dict[str, str]] = []
    for identity_id, asset_id, image, reference_kind in entries:
        path = root / "assets" / f"{asset_id}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        write_bgr_png(path, image)
        assets.append(
            {
                "asset_id": asset_id,
                "asset_reference": f"assets/{asset_id}.png",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "provenance": "synthetic-generated",
            }
        )
        identity_key = "strategy_id" if kind == "strategy" else "avatar_id"
        references.append(
            {
                identity_key: identity_id,
                "asset_id": asset_id,
                "reference_kind": reference_kind,
            }
        )
    document = {
        "schema_version": 1,
        "kind": kind,
        "assets": assets,
        "strategy_references": references if kind == "strategy" else [],
        "avatar_references": references if kind == "avatar" else [],
    }
    path = root / "catalog.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def _matcher(
    tmp_path: Path,
    entries: list[tuple[str, str, np.ndarray, str]],
    *,
    config: LocalFeatureMatcherConfig | None = None,
    kind: str = "strategy",
) -> LocalFeatureVisualMatcher:
    return LocalFeatureVisualMatcher(
        load_visual_reference_catalog(_write_catalog(tmp_path, entries, kind=kind)),
        config,
    )


def test_recovers_isotropic_scale_and_translation_for_correct_identity(tmp_path: Path) -> None:
    query = _textured_image(1)
    matcher = _matcher(
        tmp_path,
        [
            (
                "strategy.synthetic.correct",
                "asset.synthetic.correct",
                _transformed_reference(query, scale=1.35, x_translation=24, y_translation=18),
                "selection_render",
            ),
            (
                "strategy.synthetic.wrong",
                "asset.synthetic.wrong",
                _transformed_reference(_textured_image(9)),
                "canonical_web",
            ),
        ],
    )

    result = matcher.match(query, query_reference="synthetic-query")

    assert result.status is VisualMatchStatus.MATCHED
    assert result.selected_identity is not None
    assert result.selected_identity.identity_id == "strategy.synthetic.correct"
    evidence = result.selected_identity.best_reference
    assert evidence.geometry_valid
    assert evidence.scale == pytest.approx(1.35, abs=0.08)
    assert evidence.x_translation == pytest.approx(24, abs=4)
    assert evidence.y_translation == pytest.approx(18, abs=4)


def test_recovers_small_allowed_rotation(tmp_path: Path) -> None:
    query = _textured_image(2)
    matcher = _matcher(
        tmp_path,
        [
            (
                "strategy.synthetic.rotated",
                "asset.synthetic.rotated",
                _transformed_reference(query, rotation_degrees=3.0),
                "other_explicit_render_context",
            )
        ],
    )

    result = matcher.match(query, query_reference="synthetic-rotation")

    assert result.status is VisualMatchStatus.MATCHED
    assert result.selected_identity is not None
    assert result.selected_identity.best_reference.rotation_degrees == pytest.approx(3, abs=1)


def test_unrelated_identity_and_feature_poor_query_are_unresolved(tmp_path: Path) -> None:
    matcher = _matcher(
        tmp_path,
        [
            (
                "strategy.synthetic.unrelated",
                "asset.synthetic.unrelated",
                _transformed_reference(_unrelated_image()),
                "canonical_web",
            )
        ],
    )

    unrelated = matcher.match(_textured_image(3), query_reference="unrelated")
    blank = matcher.match(np.zeros((70, 88, 3), dtype=np.uint8), query_reference="blank")

    assert unrelated.status is VisualMatchStatus.UNRESOLVED
    assert blank.status is VisualMatchStatus.UNRESOLVED
    assert blank.reference_candidates[0].rejection_reason is (
        LocalFeatureRejectionReason.QUERY_NO_DESCRIPTORS
    )


def test_consensus_and_physical_transform_constraints_reject_invalid_candidates(
    tmp_path: Path,
) -> None:
    query = _textured_image(4)
    scale_matcher = _matcher(
        tmp_path / "scale",
        [
            (
                "strategy.synthetic.scale",
                "asset.synthetic.scale",
                _transformed_reference(query, scale=1.80, x_translation=8, y_translation=10),
                "selection_render",
            )
        ],
    )
    rotation_matcher = _matcher(
        tmp_path / "rotation",
        [
            (
                "strategy.synthetic.rotation",
                "asset.synthetic.rotation",
                _transformed_reference(query, rotation_degrees=12),
                "selection_render",
            )
        ],
    )
    consensus_matcher = _matcher(
        tmp_path / "consensus",
        [
            (
                "strategy.synthetic.consensus",
                "asset.synthetic.consensus",
                _transformed_reference(query),
                "selection_render",
            )
        ],
        config=LocalFeatureMatcherConfig(minimum_inliers=500),
    )

    scale = scale_matcher.match(query, query_reference="invalid-scale")
    rotation = rotation_matcher.match(query, query_reference="invalid-rotation")
    consensus = consensus_matcher.match(query, query_reference="insufficient-consensus")

    assert scale.status is VisualMatchStatus.UNRESOLVED
    assert scale.reference_candidates[0].rejection_reason is (
        LocalFeatureRejectionReason.SCALE_OUT_OF_RANGE
    )
    assert rotation.status is VisualMatchStatus.UNRESOLVED
    assert rotation.reference_candidates[0].rejection_reason is (
        LocalFeatureRejectionReason.ROTATION_OUT_OF_RANGE
    )
    assert consensus.status is VisualMatchStatus.UNRESOLVED
    assert consensus.reference_candidates[0].rejection_reason is (
        LocalFeatureRejectionReason.INSUFFICIENT_RATIO_MATCHES
    )


def test_too_few_ransac_inliers_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    query = _textured_image(45)
    matcher = _matcher(
        tmp_path,
        [
            (
                "strategy.synthetic.low-consensus",
                "asset.synthetic.low-consensus",
                _transformed_reference(query),
                "selection_render",
            )
        ],
        config=LocalFeatureMatcherConfig(minimum_inliers=4),
    )

    def insufficient_consensus(
        source_points: np.ndarray,
        _target_points: np.ndarray,
        **_kwargs: object,
    ) -> tuple[np.ndarray, np.ndarray]:
        mask = np.zeros((source_points.shape[0], 1), dtype=np.uint8)
        mask[:2] = 1
        transform = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float64)
        return transform, mask

    monkeypatch.setattr(cv2, "estimateAffinePartial2D", insufficient_consensus)

    result = matcher.match(query, query_reference="low-geometric-consensus")

    assert result.status is VisualMatchStatus.UNRESOLVED
    assert result.reference_candidates[0].ransac_inlier_count == 2
    assert result.reference_candidates[0].rejection_reason is (
        LocalFeatureRejectionReason.INSUFFICIENT_INLIERS
    )


def test_same_identity_references_aggregate_without_self_ambiguity_and_are_cached(
    tmp_path: Path,
) -> None:
    query = _textured_image(5)
    matcher = _matcher(
        tmp_path,
        [
            (
                "strategy.synthetic.shared",
                "asset.synthetic.weak",
                _transformed_reference(_textured_image(50)),
                "canonical_web",
            ),
            (
                "strategy.synthetic.shared",
                "asset.synthetic.strong",
                _transformed_reference(query),
                "selection_render",
            ),
        ],
        config=LocalFeatureMatcherConfig(ambiguity_margin=1.0),
    )

    first = matcher.match(query, query_reference="first")
    second = matcher.match(query, query_reference="second")

    assert matcher.cached_reference_asset_ids == (
        "asset.synthetic.strong",
        "asset.synthetic.weak",
    )
    assert first.status is VisualMatchStatus.MATCHED
    assert second.status is VisualMatchStatus.MATCHED
    assert len(first.identity_candidates) == 1
    assert first.selected_identity is not None
    assert first.selected_identity.best_reference.asset_id == "asset.synthetic.strong"


def test_close_different_identities_are_ambiguous_with_explicit_policy(tmp_path: Path) -> None:
    query = _textured_image(6)
    reference = _transformed_reference(query)
    matcher = _matcher(
        tmp_path,
        [
            (
                "avatar.synthetic.first",
                "asset.synthetic.first",
                reference,
                "battle_render",
            ),
            (
                "avatar.synthetic.second",
                "asset.synthetic.second",
                reference.copy(),
                "battle_render",
            ),
        ],
        config=LocalFeatureMatcherConfig(ambiguity_margin=0.01),
        kind="avatar",
    )

    result = matcher.match(query, query_reference="ambiguous-avatar")

    assert result.status is VisualMatchStatus.AMBIGUOUS
    assert result.selected_identity is None
    assert len(result.identity_candidates) == 2


def test_unicode_query_path_report_and_cli_configuration(tmp_path: Path) -> None:
    query = _textured_image(7)
    root = tmp_path / "日本語-策略"
    matcher = _matcher(
        root,
        [
            (
                "strategy.synthetic.unicode",
                "asset.synthetic.unicode",
                _transformed_reference(query),
                "selection_render",
            )
        ],
    )
    query_path = root / "照会-クエリ.png"
    write_bgr_png(query_path, query)

    result = matcher.match_path(query_path)
    report_path = write_local_feature_match_report(result, root / "出力")
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    args = build_parser().parse_args(
        [
            "visual-local-feature-match",
            "--kind",
            "strategy",
            "--catalog",
            "synthetic-catalog.yaml",
            "--image",
            "synthetic-query.png",
            "--output",
            "synthetic-output",
            "--minimum-inliers",
            "4",
            "--ambiguity-margin",
            "0.05",
        ]
    )

    assert result.status is VisualMatchStatus.MATCHED
    assert payload["matcher"]["transform_direction"] == "query_to_reference"
    assert payload["catalog_fingerprint"] == matcher.catalog.fingerprint
    assert payload["reference_candidates"][0]["reference_kind"] == "selection_render"
    assert args.command == "visual-local-feature-match"
    assert args.minimum_inliers == 4
    assert args.ambiguity_margin == 0.05
