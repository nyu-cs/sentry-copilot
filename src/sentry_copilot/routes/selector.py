from __future__ import annotations

from .models import MapDefinition, RouteCondition, RouteDefinition, RouteQuery


class RouteSelector:
    """Deterministically select routes for an explicit map and encounter context."""

    def select(self, map_definition: MapDefinition, query: RouteQuery) -> list[RouteDefinition]:
        if map_definition.map_id != query.map_id:
            raise ValueError(
                f"query map {query.map_id!r} does not match definition {map_definition.map_id!r}"
            )
        if map_definition.ruleset_ids and query.ruleset_id not in map_definition.ruleset_ids:
            raise ValueError(
                f"ruleset {query.ruleset_id!r} is not supported by map {map_definition.map_id!r}"
            )
        routes = [
            route
            for route in map_definition.routes
            if route.actor_type == query.actor_type
            and self._actor_matches(route, query)
            and self._condition_matches(route.conditions, query)
        ]
        return sorted(routes, key=lambda route: (-route.priority, route.route_id))

    @staticmethod
    def _actor_matches(route: RouteDefinition, query: RouteQuery) -> bool:
        if not route.actor_ids:
            return True
        return query.actor_id in route.actor_ids

    @staticmethod
    def _condition_matches(condition: RouteCondition, query: RouteQuery) -> bool:
        if condition.stage_types and query.stage_type not in condition.stage_types:
            return False
        if condition.waves and query.wave not in condition.waves:
            return False
        if condition.enemy_profiles and not (condition.enemy_profiles & query.enemy_profiles):
            return False
        if condition.boss_phases and query.boss_phase not in condition.boss_phases:
            return False
        return True
