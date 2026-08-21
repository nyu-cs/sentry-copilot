from __future__ import annotations

from pathlib import Path

from sentry_copilot.cli import build_parser


def test_visual_catalog_match_accepts_an_explicit_strategy_catalog_only() -> None:
    args = build_parser().parse_args(
        [
            "visual-catalog-match",
            "--kind",
            "strategy",
            "--strategy-catalog",
            "synthetic-strategy-catalog.yaml",
            "--catalog",
            "synthetic-visual-catalog.yaml",
            "--image",
            "synthetic-query.png",
            "--output",
            "synthetic-output",
        ]
    )

    assert args.strategy_catalog == Path("synthetic-strategy-catalog.yaml")
    assert args.catalog == Path("synthetic-visual-catalog.yaml")
