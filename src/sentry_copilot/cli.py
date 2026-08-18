from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

from sentry_copilot.capture.display_smoke import (
    DisplayCaptureSmokeConfig,
    run_display_capture_smoke_test,
)
from sentry_copilot.capture.windows_display import WindowsDisplayFrameSource
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
from sentry_copilot.vision.live_ocr_probe import LiveOcrProbeConfig, run_live_ocr_probe
from sentry_copilot.vision.ocr import check_windows_ocr_language
from sentry_copilot.vision.validation_runner import (
    OfflineValidationConfig,
    parse_named_roi,
    run_offline_validation,
)
from sentry_copilot.vision.viewport import NormalizedRoi, PixelRoi


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sentry-copilot")
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate-data", help="Validate map YAML files")
    validate.add_argument("--maps", type=Path, required=True)

    demo = commands.add_parser("demo-route-overlay", help="Render routes on a synthetic frame")
    demo.add_argument("--map-file", type=Path, required=True)
    demo.add_argument("--output", type=Path, required=True)
    validate_frames = commands.add_parser(
        "validate-frames", help="Run explicit local frames through viewport/ROI debug"
    )
    validate_frames.add_argument("--source", type=Path, required=True)
    validate_frames.add_argument("--output", type=Path, required=True)
    viewport = validate_frames.add_mutually_exclusive_group(required=True)
    viewport.add_argument("--full-frame", action="store_true")
    viewport.add_argument("--viewport", nargs=4, type=int, metavar=("X", "Y", "W", "H"))
    validate_frames.add_argument("--sample-every", type=int, default=1, metavar="N")
    validate_frames.add_argument(
        "--roi",
        action="append",
        default=[],
        metavar="NAME=X,Y,W,H",
        help="normalized ROI; may be repeated",
    )
    capture_display = commands.add_parser(
        "capture-display", help="Run a bounded read-only Windows physical-display capture"
    )
    capture_display.add_argument("--monitor", type=int, default=1, metavar="INDEX")
    capture_display.add_argument("--target-fps", type=float, default=5.0, metavar="FPS")
    limit = capture_display.add_mutually_exclusive_group(required=True)
    limit.add_argument("--duration-seconds", type=float, metavar="SECONDS")
    limit.add_argument("--frame-limit", type=int, metavar="COUNT")
    capture_display.add_argument(
        "--start-delay-seconds", type=float, default=0.0, metavar="SECONDS"
    )
    capture_display.add_argument("--output", type=Path, required=True)
    capture_display.add_argument("--dump-every", type=int, metavar="N")
    check_ocr_language = commands.add_parser(
        "check-ocr-language",
        help="Check a local Windows OCR language capability without installing it",
    )
    check_ocr_language.add_argument("--language", required=True, metavar="BCP47")
    live_ocr_probe = commands.add_parser(
        "live-ocr-probe", help="Capture one display frame and OCR one explicit ROI"
    )
    live_ocr_probe.add_argument("--monitor", type=int, required=True, metavar="INDEX")
    live_ocr_probe.add_argument("--language", required=True, metavar="BCP47")
    live_ocr_probe.add_argument(
        "--start-delay-seconds", type=float, default=0.0, metavar="SECONDS"
    )
    live_ocr_probe.add_argument("--output", type=Path, required=True)
    roi = live_ocr_probe.add_mutually_exclusive_group(required=True)
    roi.add_argument("--normalized-roi", nargs=4, type=float, metavar=("X", "Y", "W", "H"))
    roi.add_argument("--pixel-roi", nargs=4, type=int, metavar=("X", "Y", "W", "H"))
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "validate-data":
        repository = MapRepository.from_directory(args.maps)
        print(f"validated {len(repository.list_ids())} map(s): {', '.join(repository.list_ids())}")
    elif args.command == "demo-route-overlay":
        demo_route_overlay(args.map_file, args.output)
    elif args.command == "validate-frames":
        viewport_pixel_roi = PixelRoi(*args.viewport) if args.viewport is not None else None
        config = OfflineValidationConfig(
            source_path=args.source,
            output_directory=args.output,
            full_frame=args.full_frame,
            viewport_pixel_roi=viewport_pixel_roi,
            rois=tuple(parse_named_roi(value) for value in args.roi),
            sample_every_n=args.sample_every,
        )
        validation_result = run_offline_validation(config)
        print(
            f"wrote {validation_result.manifest_path} "
            f"({validation_result.selected_frame_count} frame(s))"
        )
    elif args.command == "capture-display":
        source = WindowsDisplayFrameSource(
            monitor_index=args.monitor,
            target_fps=args.target_fps,
        )
        capture_result = run_display_capture_smoke_test(
            source,
            DisplayCaptureSmokeConfig(
                output_directory=args.output,
                duration_seconds=args.duration_seconds,
                frame_limit=args.frame_limit,
                start_delay_seconds=args.start_delay_seconds,
                dump_every_n=args.dump_every,
            ),
        )
        print(
            f"wrote {capture_result.manifest_path} "
            f"({capture_result.captured_frame_count} frame(s))"
        )
    elif args.command == "check-ocr-language":
        capability = check_windows_ocr_language(args.language)
        print(
            f"{capability.language_tag}: {capability.status.value}"
            + (f" ({capability.reason})" if capability.reason is not None else "")
        )
    elif args.command == "live-ocr-probe":
        roi = (
            NormalizedRoi(*args.normalized_roi)
            if args.normalized_roi is not None
            else PixelRoi(*args.pixel_roi)
        )
        probe_result = run_live_ocr_probe(
            WindowsDisplayFrameSource(monitor_index=args.monitor),
            LiveOcrProbeConfig(
                output_directory=args.output,
                roi=roi,
                language_tag=args.language,
                start_delay_seconds=args.start_delay_seconds,
            ),
        )
        print(f"wrote {probe_result.result_path} ({probe_result.outcome.value})")
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
