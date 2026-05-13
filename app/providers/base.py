from __future__ import annotations

from typing import Protocol

from app.domain.models import Activity, Coordinates, Restaurant, RouteOption


class ProviderAPIError(RuntimeError):
    """Raised when a real provider call fails and the agent should not fall back."""


class LocalLifeProvider(Protocol):
    def search_activities(
        self,
        tags: list[str],
        party_size: int,
        radius_km: float,
        origin: Coordinates | None = None,
    ) -> list[Activity]:
        ...

    def search_restaurants(
        self,
        tags: list[str],
        party_size: int,
        radius_km: float,
        origin: Coordinates | None = None,
    ) -> list[Restaurant]:
        ...

    def calculate_routes(
        self,
        origin_name: str,
        origin: Coordinates,
        destination_name: str,
        destination: Coordinates,
        modes: list[str],
    ) -> list[RouteOption]:
        ...

    def book_activity(self, activity_id: str, payload: dict) -> dict:
        ...

    def reserve_restaurant(self, restaurant_id: str, payload: dict) -> dict:
        ...

    def send_notification(self, payload: dict) -> dict:
        ...
