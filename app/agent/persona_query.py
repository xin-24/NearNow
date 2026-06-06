from __future__ import annotations

from dataclasses import dataclass, field

from app.agent.context_builder import PlanningContext
from app.domain.models import Activity, Restaurant
from app.utils.text import unique_strings


@dataclass(frozen=True)
class PersonaSearchProfile:
    activity_tags: list[str] = field(default_factory=list)
    restaurant_tags: list[str] = field(default_factory=list)
    min_activities: int = 4
    min_restaurants: int = 5
    max_radius_km: float = 12.0
    expansion_factor: float = 1.6


class PersonaQueryPlanner:
    """Turns participant profiles into richer search intents before provider lookup."""

    def build(self, context: PlanningContext) -> PersonaSearchProfile:
        relations = {participant.relation for participant in context.intent.participants}
        preferences = set(context.intent.preferences)
        activity_tags: list[str] = []
        restaurant_tags: list[str] = []
        min_activities = 4
        min_restaurants = 5

        if "elder" in relations:
            activity_tags.extend(["公园", "花园", "商场", "散步", "慢走", "stroll_friendly", "low_walking"])
            restaurant_tags.extend(["proper_meal", "light_food", "elder_friendly", "清淡", "粥", "中餐"])
            min_activities = max(min_activities, 5)
            min_restaurants = max(min_restaurants, 6)

        if "pet" in relations:
            activity_tags.extend(["宠物", "遛狗", "狗公园", "公园", "pet_friendly", "outdoor"])
            restaurant_tags.extend(["pet_friendly", "pet_possible", "outdoor", "takeaway_possible", "咖啡", "外带"])
            min_activities = max(min_activities, 3)
            min_restaurants = max(min_restaurants, 5)

        if "child" in relations:
            activity_tags.extend(["亲子", "儿童", "游乐场", "公园", "博物馆", "kid_friendly", "child_safe"])
            restaurant_tags.extend(["kid_friendly", "group_table", "proper_meal", "少排队"])

        if "bestie" in relations:
            activity_tags.extend(["下午茶", "咖啡", "展览", "商场", "拍照", "photo_friendly", "chat_friendly"])
            restaurant_tags.extend(["afternoon_tea", "bestie", "chat_friendly", "quiet", "甜品", "咖啡"])

        if "partner" in relations:
            activity_tags.extend(["展览", "电影", "剧场", "公园", "约会", "date", "quiet"])
            restaurant_tags.extend(["date", "quiet", "proper_meal", "light_food"])

        if "friend_group" in relations or "colleague" in relations:
            activity_tags.extend(["商场", "团建", "运动", "team_building", "group_friendly"])
            restaurant_tags.extend(["group_table", "budget_control", "proper_meal"])
            min_restaurants = max(min_restaurants, 6)

        if "stroll" in preferences:
            activity_tags.extend(["公园", "花园", "商场", "散步", "慢走"])
        if "proper_meal" in preferences:
            restaurant_tags.extend(["proper_meal", "餐厅"])
        if "light_food" in preferences or "low_calorie" in preferences:
            restaurant_tags.extend(["light_food", "清淡", "轻食"])

        return PersonaSearchProfile(
            activity_tags=unique_strings(activity_tags),
            restaurant_tags=unique_strings(restaurant_tags),
            min_activities=min_activities,
            min_restaurants=min_restaurants,
        )


@dataclass(frozen=True)
class CandidateQualityReport:
    notes: list[str]
    expanded_radius_km: float | None = None


class CandidateQualityGate:
    """Diagnoses sparse or weakly labeled provider candidates without changing the API contract."""

    def evaluate(
        self,
        context: PlanningContext,
        activities: list[Activity],
        restaurants: list[Restaurant],
        activity_targets: set[str],
        restaurant_targets: set[str],
        profile: PersonaSearchProfile,
        expanded_radius_km: float | None = None,
    ) -> CandidateQualityReport:
        notes: list[str] = []
        if expanded_radius_km is not None:
            notes.append(f"初始半径内画像匹配候选不足，已自动扩大到约 {expanded_radius_km:g} 公里继续查找。")

        if len(activities) < profile.min_activities or len(restaurants) < profile.min_restaurants:
            notes.append("当前位置周边可用 POI 数量偏少，或地图数据覆盖不完整；建议必要时扩大商圈范围。")

        if activities and self._matching_count(activities, activity_targets) < 2:
            notes.append("活动候选的画像标签较少，已结合地点类型、名称和距离做弱推断，出发前建议复核。")

        if restaurants and self._matching_count(restaurants, restaurant_targets) < 2:
            notes.append("餐厅候选缺少完整的人均、评分、营业和偏好标签，当前按名称、类型和距离综合排序。")

        if self._dominant_activity_category_ratio(activities) >= 0.75 and len(activities) >= 4:
            notes.append("附近活动类型较集中，系统已优先保留不同类型的备选，避免只推荐同类地点。")

        return CandidateQualityReport(notes=unique_strings(notes, normalize_whitespace=False), expanded_radius_km=expanded_radius_km)

    def needs_expansion(
        self,
        activities: list[Activity],
        restaurants: list[Restaurant],
        activity_targets: set[str],
        restaurant_targets: set[str],
        profile: PersonaSearchProfile,
    ) -> bool:
        if len(activities) < profile.min_activities or len(restaurants) < profile.min_restaurants:
            return True
        return self._matching_count(activities, activity_targets) < 2 or self._matching_count(restaurants, restaurant_targets) < 2

    def _matching_count(self, candidates: list[Activity] | list[Restaurant], targets: set[str]) -> int:
        if not targets:
            return len(candidates)
        return sum(1 for candidate in candidates if set(candidate.tags) & targets)

    def _dominant_activity_category_ratio(self, activities: list[Activity]) -> float:
        if not activities:
            return 0
        counts: dict[str, int] = {}
        for activity in activities:
            counts[activity.category] = counts.get(activity.category, 0) + 1
        return max(counts.values()) / len(activities)
