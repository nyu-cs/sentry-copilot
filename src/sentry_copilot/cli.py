from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

from sentry_copilot.capture.display_smoke import (
    DisplayCaptureSmokeConfig,
    run_display_capture_smoke_test,
)
from sentry_copilot.capture.frame_source import ImageSequenceFrameSource
from sentry_copilot.capture.video_frame_extraction import (
    VideoFrameExtractionConfig,
    VideoFrameRequest,
    extract_video_frames,
)
from sentry_copilot.capture.windows_display import WindowsDisplayFrameSource
from sentry_copilot.catalogs.repository import load_catalog
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
from sentry_copilot.vision.local_feature_matching import (
    LocalFeatureMatcherConfig,
    LocalFeatureMatchError,
    LocalFeatureVisualMatcher,
    write_local_feature_match_report,
)
from sentry_copilot.vision.ocr import check_windows_ocr_language
from sentry_copilot.vision.recognition_probe import (
    OcrProbeOperation,
    RecognitionProbeConfig,
    RecognitionProbeConfigurationError,
    TemplateProbeOperation,
    load_template_image,
    run_recognition_probe,
)
from sentry_copilot.vision.validation_runner import (
    OfflineValidationConfig,
    parse_named_roi,
    run_offline_validation,
)
from sentry_copilot.vision.viewport import NormalizedRoi, PixelRoi
from sentry_copilot.vision.visual_references import (
    VisualCatalogKind,
    VisualCatalogLoadError,
    VisualCatalogValidationError,
    load_visual_reference_catalog,
    match_visual_catalog,
    write_visual_match_report,
)


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
    live_ocr_probe.add_argument("--start-delay-seconds", type=float, default=0.0, metavar="SECONDS")
    live_ocr_probe.add_argument("--output", type=Path, required=True)
    roi = live_ocr_probe.add_mutually_exclusive_group(required=True)
    roi.add_argument("--normalized-roi", nargs=4, type=float, metavar=("X", "Y", "W", "H"))
    roi.add_argument("--pixel-roi", nargs=4, type=int, metavar=("X", "Y", "W", "H"))
    recognition_probe = commands.add_parser(
        "recognition-probe", help="Run explicit generic OCR/template operations over one frame"
    )
    source = recognition_probe.add_mutually_exclusive_group(required=True)
    source.add_argument("--image", type=Path, metavar="PATH")
    source.add_argument("--monitor", type=int, metavar="INDEX")
    recognition_probe.add_argument("--output", type=Path, required=True)
    recognition_probe.add_argument("--language", metavar="BCP47")
    recognition_probe.add_argument(
        "--start-delay-seconds", type=float, default=0.0, metavar="SECONDS"
    )
    recognition_probe.add_argument("--annotated-diagnostic", action="store_true")
    recognition_probe.add_argument("--template-threshold", type=float, default=0.9)
    recognition_probe.add_argument(
        "--ocr-normalized-roi",
        action="append",
        default=[],
        nargs=5,
        metavar=("NAME", "X", "Y", "W", "H"),
    )
    recognition_probe.add_argument(
        "--ocr-pixel-roi",
        action="append",
        default=[],
        nargs=5,
        metavar=("NAME", "X", "Y", "W", "H"),
    )
    recognition_probe.add_argument(
        "--template-normalized-roi",
        action="append",
        default=[],
        nargs=6,
        metavar=("NAME", "X", "Y", "W", "H", "TEMPLATE"),
    )
    recognition_probe.add_argument(
        "--template-pixel-roi",
        action="append",
        default=[],
        nargs=6,
        metavar=("NAME", "X", "Y", "W", "H", "TEMPLATE"),
    )
    extract_video_frames = commands.add_parser(
        "extract-video-frames",
        help="Extract explicit full-resolution PNG frames from one local video",
    )
    extract_video_frames.add_argument("--video", type=Path, required=True, metavar="PATH")
    visual_catalog_match = commands.add_parser(
        "visual-catalog-match",
        help="Match one explicit image against an explicit visual reference catalog",
    )
    visual_catalog_match.add_argument(
        "--kind", choices=[kind.value for kind in VisualCatalogKind], required=True
    )
    visual_catalog_match.add_argument("--catalog", type=Path, required=True)
    visual_catalog_match.add_argument(
        "--strategy-catalog",
        type=Path,
        metavar="PATH",
        help="optional exact strategy catalog used to validate strategy references",
    )
    visual_catalog_match.add_argument("--image", type=Path, required=True)
    visual_catalog_match.add_argument("--output", type=Path, required=True)
    visual_catalog_match.add_argument("--minimum-score", type=float, default=0.9)
    visual_catalog_match.add_argument("--ambiguity-margin", type=float, default=0.02)
    visual_local_feature_match = commands.add_parser(
        "visual-local-feature-match",
        help="Match one explicit image using catalog-backed SIFT and similarity RANSAC",
    )
    visual_local_feature_match.add_argument(
        "--kind", choices=[kind.value for kind in VisualCatalogKind], required=True
    )
    visual_local_feature_match.add_argument("--catalog", type=Path, required=True)
    visual_local_feature_match.add_argument(
        "--strategy-catalog",
        type=Path,
        metavar="PATH",
        help="optional exact strategy catalog used to validate strategy references",
    )
    visual_local_feature_match.add_argument("--image", type=Path, required=True)
    visual_local_feature_match.add_argument("--output", type=Path, required=True)
    visual_local_feature_match.add_argument("--sift-nfeatures", type=int, default=300)
    visual_local_feature_match.add_argument(
        "--sift-contrast-threshold", type=float, default=0.02
    )
    visual_local_feature_match.add_argument("--sift-edge-threshold", type=float, default=10.0)
    visual_local_feature_match.add_argument("--lowe-ratio", type=float, default=0.75)
    visual_local_feature_match.add_argument(
        "--ransac-reprojection-threshold", type=float, default=3.0
    )
    visual_local_feature_match.add_argument("--minimum-scale", type=float, default=0.80)
    visual_local_feature_match.add_argument("--maximum-scale", type=float, default=1.60)
    visual_local_feature_match.add_argument("--maximum-rotation-degrees", type=float, default=5.0)
    visual_local_feature_match.add_argument("--minimum-inliers", type=int, default=3)
    visual_local_feature_match.add_argument("--minimum-inlier-ratio", type=float, default=0.0)
    visual_local_feature_match.add_argument("--ambiguity-margin", type=float, default=0.0)
    extract_video_frames.add_argument("--output", type=Path, required=True, metavar="PATH")
    extract_video_frames.add_argument(
        "--at",
        action="append",
        required=True,
        nargs=2,
        metavar=("HH:MM:SS[.mmm]", "LABEL"),
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
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
            f"wrote {capture_result.manifest_path} ({capture_result.captured_frame_count} frame(s))"
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
    elif args.command == "recognition-probe":
        try:
            operations = _recognition_probe_operations(args)
            if args.image is not None and args.start_delay_seconds:
                raise RecognitionProbeConfigurationError(
                    "start-delay-seconds is available only with a live --monitor source"
                )
            recognition_source = (
                ImageSequenceFrameSource((args.image,), source_id=f"local-image:{args.image.name}")
                if args.image is not None
                else WindowsDisplayFrameSource(monitor_index=args.monitor)
            )
            recognition_probe_result = run_recognition_probe(
                recognition_source,
                RecognitionProbeConfig(
                    output_directory=args.output,
                    operations=operations,
                    start_delay_seconds=args.start_delay_seconds,
                    write_annotated_diagnostic=args.annotated_diagnostic,
                ),
            )
        except RecognitionProbeConfigurationError as error:
            parser.error(str(error))
        print(
            "wrote "
            f"{recognition_probe_result.report_path} "
            f"({len(recognition_probe_result.operations)} operation(s))"
        )
    elif args.command == "visual-catalog-match":
        try:
            strategy_catalog = (
                load_catalog(args.strategy_catalog).catalog
                if args.strategy_catalog is not None
                else None
            )
            visual_catalog = load_visual_reference_catalog(
                args.catalog,
                strategy_catalog=strategy_catalog,
            )
            actual_kind = visual_catalog.kind.value
            if actual_kind != args.kind:
                raise ValueError(
                    f"requested kind {args.kind} does not match catalog kind {actual_kind}"
                )
            visual_match = match_visual_catalog(
                catalog=visual_catalog,
                query_path=args.image,
                minimum_score=args.minimum_score,
                ambiguity_margin=args.ambiguity_margin,
            )
            report_path = write_visual_match_report(visual_match, args.output)
        except (VisualCatalogLoadError, VisualCatalogValidationError, ValueError) as error:
            parser.error(str(error))
        print(f"wrote {report_path} ({visual_match.status.value})")
    elif args.command == "visual-local-feature-match":
        try:
            strategy_catalog = (
                load_catalog(args.strategy_catalog).catalog
                if args.strategy_catalog is not None
                else None
            )
            visual_catalog = load_visual_reference_catalog(
                args.catalog,
                strategy_catalog=strategy_catalog,
            )
            actual_kind = visual_catalog.kind.value
            if actual_kind != args.kind:
                raise ValueError(
                    f"requested kind {args.kind} does not match catalog kind {actual_kind}"
                )
            local_feature_matcher = LocalFeatureVisualMatcher(
                visual_catalog,
                LocalFeatureMatcherConfig(
                    sift_nfeatures=args.sift_nfeatures,
                    sift_contrast_threshold=args.sift_contrast_threshold,
                    sift_edge_threshold=args.sift_edge_threshold,
                    lowe_ratio=args.lowe_ratio,
                    ransac_reprojection_threshold=args.ransac_reprojection_threshold,
                    minimum_scale=args.minimum_scale,
                    maximum_scale=args.maximum_scale,
                    maximum_abs_rotation_degrees=args.maximum_rotation_degrees,
                    minimum_inliers=args.minimum_inliers,
                    minimum_inlier_ratio=args.minimum_inlier_ratio,
                    ambiguity_margin=args.ambiguity_margin,
                ),
            )
            local_feature_match = local_feature_matcher.match_path(args.image)
            report_path = write_local_feature_match_report(local_feature_match, args.output)
        except (
            LocalFeatureMatchError,
            VisualCatalogLoadError,
            VisualCatalogValidationError,
            ValueError,
        ) as error:
            parser.error(str(error))
        print(f"wrote {report_path} ({local_feature_match.status.value})")
    elif args.command == "extract-video-frames":
        try:
            extraction_result = extract_video_frames(
                VideoFrameExtractionConfig(
                    video_path=args.video,
                    output_directory=args.output,
                    requests=tuple(
                        VideoFrameRequest(timestamp_text=timestamp, label=label)
                        for timestamp, label in args.at
                    ),
                )
            )
        except ValueError as error:
            parser.error(str(error))
        successful = sum(record.status.value == "success" for record in extraction_result.records)
        print(f"wrote {extraction_result.manifest_path} ({successful} frame(s) extracted)")
    else:  # pragma: no cover
        raise AssertionError("unreachable")


def _recognition_probe_operations(
    args: argparse.Namespace,
) -> tuple[OcrProbeOperation | TemplateProbeOperation, ...]:
    operations: list[OcrProbeOperation | TemplateProbeOperation] = []
    if (args.ocr_normalized_roi or args.ocr_pixel_roi) and args.language is None:
        raise RecognitionProbeConfigurationError("--language is required for OCR probe operations")
    for values in args.ocr_normalized_roi:
        name, x, y, width, height = values
        operations.append(
            OcrProbeOperation(
                name=name,
                roi=NormalizedRoi(float(x), float(y), float(width), float(height)),
                language_tag=args.language,
            )
        )
    for values in args.ocr_pixel_roi:
        name, x, y, width, height = values
        operations.append(
            OcrProbeOperation(
                name=name,
                roi=PixelRoi(int(x), int(y), int(width), int(height)),
                language_tag=args.language,
            )
        )
    for values in args.template_normalized_roi:
        name, x, y, width, height, template_path = values
        template = load_template_image(template_path)
        operations.append(
            TemplateProbeOperation(
                name=name,
                roi=NormalizedRoi(float(x), float(y), float(width), float(height)),
                template=template,
                template_reference=template_path,
                threshold=args.template_threshold,
            )
        )
    for values in args.template_pixel_roi:
        name, x, y, width, height, template_path = values
        template = load_template_image(template_path)
        operations.append(
            TemplateProbeOperation(
                name=name,
                roi=PixelRoi(int(x), int(y), int(width), int(height)),
                template=template,
                template_reference=template_path,
                threshold=args.template_threshold,
            )
        )
    return tuple(operations)


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
