from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import Coordinates, PlanningIntent, PlanningStrategy, UserContext


@dataclass
class PlanningContext:
    intent: PlanningIntent
    user_context: UserContext
    origin_name: str
    origin_coordinates: Coordinates
    strategy: PlanningStrategy | None = None


class ContextBuilder:
    def build(
        self,
        intent: PlanningIntent,
        user_context_payload: dict | None,
        strategy: PlanningStrategy | None = None,
    ) -> PlanningContext | dict:
        payload = user_context_payload or {}
        home_location = self._normalize_location_text(payload.get("home_location"))
        city = self._normalize_location_text(payload.get("city", "北京")) or "北京"
        coordinates_payload = payload.get("coordinates") or {}
        location_permission_granted = bool(payload.get("location_permission_granted", False))
        location_source = payload.get("location_source") or ("browser" if location_permission_granted else "manual")

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
            location_permission_granted=location_permission_granted,
            location_source=location_source,
            accuracy_m=payload.get("accuracy_m"),
            precision=payload.get("precision", "manual"),
            manual_location_format=payload.get("manual_location_format"),
            district=self._normalize_location_text(payload.get("district")),
            landmark=self._normalize_location_text(payload.get("landmark")),
            formatted_address=self._normalize_location_text(payload.get("formatted_address")),
            address_source=payload.get("address_source"),
            address_confidence=payload.get("address_confidence"),
        )
        return PlanningContext(
            intent=intent,
            user_context=user_context,
            origin_name=self._origin_name(user_context),
            origin_coordinates=coordinates,
            strategy=strategy,
        )

    def _normalize_location_text(self, value: object | None) -> str | None:
        if value is None:
            return None
        normalized = str(value)
        for mark in ("，", ",", "、", "/", "|"):
            normalized = normalized.replace(mark, " ")
        normalized = " ".join(normalized.split())
        return normalized or None

    def _origin_name(self, user_context: UserContext) -> str:
        if user_context.location_source == "browser" and user_context.location_permission_granted:
            if user_context.precision == "approximate":
                if user_context.home_location not in {None, "当前位置", "我的当前位置", "我的大概位置"}:
                    return user_context.home_location
                return "我的大概位置"
            return "我的当前位置"
        return user_context.home_location or "当前位置"
