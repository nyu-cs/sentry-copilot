from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

from sentry_copilot.domain.enums import StageType
from sentry_copilot.routes.models import (
    ActorType,
    MapCalibration,
    PixelPoint,
    RouteQuery,
)
from sentry_copilot.routes.overlay import RouteOverlayRenderer
from sentry_copilot.routes.repository import MapRepository, load_map_definition
from sentry_copilot.routes.selector import RouteSelector


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sentry-copilot")
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate-data", help="Validate map YAML files")
    validate.add_argument("--maps", type=Path, required=True)

    demo = commands.add_parser("demo-route-overlay", help="Render routes on a synthetic frame")
    demo.add_argument("--map-file", type=Path, required=True)
    demo.add_argument("--output", type=Path, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "validate-data":
        repository = MapRepository.from_directory(args.maps)
        print(f"validated {len(repository.list_ids())} map(s): {', '.join(repository.list_ids())}")
    elif args.command == "demo-route-overlay":
        demo_route_overlay(args.map_file, args.output)
    else:  # pragma: no cover
        raise AssertionError("unreachable")


def demo_route_overlay(map_file: Path, output: Path) -> None:
    map_definition = load_map_definition(map_file)
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    cv2.rectangle(frame, (100, 90), (1180, 650), (55, 55, 55), -1)
    cv2.putText(
        frame,
        "Synthetic battlefield - no game assets",
        (120, 130),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (220, 220, 220),
        2,
        lineType=cv2.LINE_AA,
    )
    calibration = MapCalibration(
        frame_width=1280,
        frame_height=720,
        battlefield_corners=[
            PixelPoint(x=100, y=90),
            PixelPoint(x=1180, y=90),
            PixelPoint(x=1180, y=650),
            PixelPoint(x=100, y=650),
        ],
        source="synthetic-demo",
    )
    selector = RouteSelector()
    enemy = selector.select(
        map_definition,
        RouteQuery(
            map_id=map_definition.map_id,
            ruleset_id="demo.v1",
            actor_type=ActorType.ENEMY,
            stage_type=StageType.REGULAR,
            wave=7,
            actor_id="enemy.generic_placeholder",
        ),
    )
    boss = selector.select(
        map_definition,
        RouteQuery(
            map_id=map_definition.map_id,
            ruleset_id="demo.v1",
            actor_type=ActorType.BOSS,
            stage_type=StageType.FINAL_BOSS,
            actor_id="boss.phantom_placeholder",
            boss_phase="phase_1",
        ),
    )
    rendered = RouteOverlayRenderer().render(frame, enemy + boss, calibration)
    output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output), rendered):
        raise RuntimeError(f"failed to write {output}")
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
