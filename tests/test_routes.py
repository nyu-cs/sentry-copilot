from pathlib import Path

import numpy as np
import pytest

from sentry_copilot.domain.enums import StageType
from sentry_copilot.routes.models import (
    ActorType,
    MapCalibration,
    PixelPoint,
    Point,
    RouteQuery,
)
from sentry_copilot.routes.projection import RouteProjector
from sentry_copilot.routes.repository import load_map_definition
from sentry_copilot.routes.selector import RouteSelector

MAP = Path("data/maps/demo.synthetic_training_map.yaml")


def test_map_loads() -> None:
    definition = load_map_definition(MAP)
    assert definition.map_id == "demo.synthetic_training_map"
    assert len(definition.routes) == 2


def test_enemy_and_boss_routes_are_selected_independently() -> None:
    definition = load_map_definition(MAP)
    selector = RouteSelector()
    enemy = selector.select(
        definition,
        RouteQuery(
            map_id=definition.map_id,
            ruleset_id="demo.v1",
            actor_type=ActorType.ENEMY,
            stage_type=StageType.REGULAR,
            wave=7,
            actor_id="enemy.generic_placeholder",
        ),
    )
    boss = selector.select(
        definition,
        RouteQuery(
            map_id=definition.map_id,
            ruleset_id="demo.v1",
            actor_type=ActorType.BOSS,
            stage_type=StageType.FINAL_BOSS,
            actor_id="boss.phantom_placeholder",
            boss_phase="phase_1",
        ),
    )
    assert [route.actor_type for route in enemy] == [ActorType.ENEMY]
    assert [route.actor_type for route in boss] == [ActorType.BOSS]


def test_projection_maps_normalized_center_to_battlefield_center() -> None:
    calibration = MapCalibration(
        frame_width=1000,
        frame_height=600,
        battlefield_corners=[
            PixelPoint(x=100, y=50),
            PixelPoint(x=900, y=50),
            PixelPoint(x=900, y=550),
            PixelPoint(x=100, y=550),
        ],
    )
    result = RouteProjector().project(Point(x=0.5, y=0.5), calibration)
    assert np.isclose(result.x, 500.0, atol=0.01)
    assert np.isclose(result.y, 300.0, atol=0.01)


def test_wrong_ruleset_is_rejected() -> None:
    definition = load_map_definition(MAP)
    with pytest.raises(ValueError, match="ruleset"):
        RouteSelector().select(
            definition,
            RouteQuery(
                map_id=definition.map_id,
                ruleset_id="wrong.version",
                actor_type=ActorType.ENEMY,
                stage_type=StageType.REGULAR,
                wave=7,
                actor_id="enemy.generic_placeholder",
            ),
        )
