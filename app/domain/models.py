from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any


def to_plain(value: Any) -> Any:
    if is_dataclass(value):
        return {key: to_plain(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [to_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: to_plain(item) for key, item in value.items()}
    return value


@dataclass
class Coordinates:
    lat: float
    lng: float


@dataclass
class Constraint:
    type: str
    value: str
    priority: str = "medium"


@dataclass
class ParticipantProfile:
    relation: str
    count: int = 1
    id: str | None = None
    age: int | None = None
    constraints: list[Constraint] = field(default_factory=list)


@dataclass
class PlanningIntent:
    message: str
    date: str = "today"
    start_time: str = "14:00"
    end_time: str = "18:00"
    participants: list[ParticipantProfile] = field(default_factory=list)
    preferences: list[str] = field(default_factory=list)
    scenario_tags: list[str] = field(default_factory=list)
    radius_km: float = 6.0
    required_actions: list[str] = field(default_factory=lambda: ["plan", "book", "notify"])

    @property
    def party_size(self) -> int:
        return sum(
            max(0, participant.count)
            for participant in self.participants
            if participant.relation != "pet"
        ) or 1


@dataclass
class UserContext:
    city: str = "北京"
    home_location: str | None = None
    coordinates: Coordinates | None = None
    location_permission_granted: bool = False


@dataclass
class Activity:
    activity_id: str
    name: str
    category: str
    location: str
    coordinates: Coordinates
    distance_km: float
    duration_minutes: int
    capacity_left: int
    tags: list[str]
    reservation_required: bool = True
    provider: str = "mock"
    provider_place_id: str | None = None


@dataclass
class Restaurant:
    restaurant_id: str
    name: str
    location: str
    coordinates: Coordinates
    distance_km: float
    available: bool
    table_size: int
    wait_minutes: int
    tags: list[str]
    reservation_required: bool = True
    average_price: int = 120
    provider: str = "mock"
    provider_place_id: str | None = None


@dataclass
class RouteOption:
    from_name: str
    to_name: str
    mode: str
    duration_minutes: int
    distance_km: float
    estimated_cost: int
    comfort_score: float
    kid_friendly_score: float
    traffic_risk: str = "low"
    walking_minutes: int = 0
    transfer_count: int = 0
    selected: bool = False


@dataclass
class ScheduleItem:
    start_time: str
    end_time: str
    type: str
    name: str
    location: str
    reason: str
    travel_minutes: int = 0
    transport_mode: str | None = None
    coordinates: Coordinates | None = None
    provider: str | None = None
    provider_place_id: str | None = None


@dataclass
class PendingAction:
    action_id: str
    type: str
    target: str
    payload: dict[str, Any]
    status: str = "pending_confirmation"


@dataclass
class Plan:
    plan_id: str
    title: str
    summary: str
    participant_summary: list[str]
    schedule: list[ScheduleItem]
    route_options: list[RouteOption]
    pending_actions: list[PendingAction]
    alternatives: list[dict[str, Any]]
    risk_notes: list[str]
    requires_confirmation: bool = True
    final_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)


@dataclass
class ExecutionResult:
    plan_id: str
    execution_status: str
    results: list[dict[str, Any]]
    final_message: str

    def to_dict(self) -> dict[str, Any]:
        return to_plain(self)
