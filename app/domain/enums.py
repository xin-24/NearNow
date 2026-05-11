from enum import StrEnum


class RunMode(StrEnum):
    MOCK = "mock"
    REAL = "real"
    HYBRID = "hybrid"


class ConstraintPriority(StrEnum):
    HARD = "hard"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TransportMode(StrEnum):
    WALKING = "walking"
    DRIVING = "driving"
    PUBLIC_TRANSIT = "public_transit"
    RIDE_HAILING = "ride_hailing"
    CYCLING = "cycling"


class ActionStatus(StrEnum):
    PENDING_CONFIRMATION = "pending_confirmation"
    SUCCESS = "success"
    FAILED = "failed"

