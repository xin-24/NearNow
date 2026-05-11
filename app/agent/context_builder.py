from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import Coordinates, PlanningIntent, UserContext


@dataclass
class PlanningContext:
    intent: PlanningIntent
    user_context: UserContext
    origin_name: str
    origin_coordinates: Coordinates


class ContextBuilder:
    def build(self, intent: PlanningIntent, user_context_payload: dict | None) -> PlanningContext | dict:
        payload = user_context_payload or {}
        home_location = payload.get("home_location")
        city = payload.get("city", "北京")
        coordinates_payload = payload.get("coordinates") or {}

        if not home_location and not coordinates_payload:
            return {
                "code": "MISSING_ORIGIN",
                "message": "可以，我需要先知道从哪里出发，才能控制距离和路线。你想从家、公司，还是某个具体地点出发？",
                "recoverable": True,
            }

        coordinates = Coordinates(
            lat=float(coordinates_payload.get("lat", 39.9957)),
            lng=float(coordinates_payload.get("lng", 116.4813)),
        )
        user_context = UserContext(
            city=city,
            home_location=home_location or "当前位置",
            coordinates=coordinates,
            location_permission_granted=bool(payload.get("location_permission_granted", False)),
        )
        return PlanningContext(
            intent=intent,
            user_context=user_context,
            origin_name=user_context.home_location or "当前位置",
            origin_coordinates=coordinates,
        )

