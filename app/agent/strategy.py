from __future__ import annotations

import json
from typing import Any

from app.utils.text import loads_json, unique_strings

from app.domain.models import PlanningIntent, PlanningStrategy, to_plain
from app.providers.longcat_client import LongCatAPIError, LongCatClient


class PersonaStrategyBuilder:
    """Builds a deterministic strategy baseline before the LLM refines it."""

    def build(self, intent: PlanningIntent) -> PlanningStrategy:
        relations = {participant.relation for participant in intent.participants}
        preferences = set(intent.preferences)
        tags = set(intent.scenario_tags)
        strategy = PlanningStrategy(
            name="balanced_local_plan",
            summary="根据同行者、距离、餐饮偏好和交通舒适度生成附近短时活动方案。",
            activity_focus=["附近活动", "动线顺畅", "可执行"],
            restaurant_focus=["附近餐厅", "座位充足"],
            preferred_activity_tags=list(tags | preferences),
            preferred_restaurant_tags=list(preferences),
            hard_constraints=[],
            soft_preferences=list(preferences),
            reasoning=[],
        )

        if "elder" in relations:
            self._merge(
                strategy,
                name="elder_stroll_light_meal",
                summary="长辈同行时优先公园、花园或商场慢逛，控制步行强度，并安排清淡正餐。",
                activity_focus=["公园散步", "花园慢逛", "商场室内慢走", "中途可休息"],
                restaurant_focus=["清淡正餐", "座位稳定", "少排队", "离活动点近"],
                preferred_activity_tags=["stroll_friendly", "low_walking", "elder_friendly", "outdoor", "indoor"],
                preferred_restaurant_tags=["proper_meal", "light_food", "elder_friendly", "group_table"],
                avoid_activity_categories=["amenity:library", "amenity:cafe", "tourism:gallery"],
                avoid_restaurant_tags=["beverage_only", "heavy_food", "quick_meal"],
                hard_constraints=["避免长距离步行和高强度活动"],
                soft_preferences=["安静", "可坐下休息", "清淡晚饭"],
                reasoning=["用户表达了爸妈、附近走走、别太累、晚饭清淡，策略应优先轻松散步和正餐。"],
            )
        elif "pet" in relations:
            self._merge(
                strategy,
                name="pet_outdoor_confirmed_plan",
                summary="携宠时活动必须宠物友好，餐厅优先明确可携宠或户外座位，并把确认宠物政策作为风险。",
                activity_focus=["公园", "狗公园", "户外低强度活动"],
                restaurant_focus=["宠物友好餐厅", "户外座位", "可外带餐厅", "到店前确认"],
                preferred_activity_tags=["pet_friendly", "outdoor", "low_walking"],
                preferred_restaurant_tags=["pet_friendly", "pet_possible", "outdoor", "takeaway_possible"],
                avoid_activity_categories=["amenity:cinema", "amenity:theatre", "tourism:gallery"],
                avoid_restaurant_tags=["heavy_food"],
                hard_constraints=["活动必须宠物友好"],
                soft_preferences=["减少宠物步行压力", "餐厅宠物政策需确认", "不确定时推荐外带/打包"],
                reasoning=["携宠场景不能把普通室内场馆当成活动；餐饮若无可携宠标签，应允许外带兜底而不是直接失败。"],
            )
        elif "bestie" in relations:
            self._merge(
                strategy,
                name="bestie_chat_photo_plan",
                summary="闺蜜场景优先拍照、聊天和下午茶空间，避免太吵或过于任务型的地点。",
                activity_focus=["咖啡", "下午茶", "展览", "商场拍照"],
                restaurant_focus=["适合聊天", "甜品或轻餐", "环境安静"],
                preferred_activity_tags=["bestie", "afternoon_tea", "chat_friendly", "photo_friendly"],
                preferred_restaurant_tags=["bestie", "afternoon_tea", "chat_friendly", "quiet"],
                avoid_activity_categories=["amenity:community_centre", "leisure:sports_centre"],
                avoid_restaurant_tags=["heavy_food", "quick_meal"],
                soft_preferences=["适合拍照", "适合聊天"],
                reasoning=["用户画像偏向轻松社交和氛围体验。"],
            )
        elif "partner" in relations:
            self._merge(
                strategy,
                name="date_atmosphere_plan",
                summary="约会场景优先安静、有氛围和低打扰地点，控制换乘和赶场感。",
                activity_focus=["展览", "电影", "剧场", "公园散步"],
                restaurant_focus=["安静正餐", "轻餐", "距离活动点近"],
                preferred_activity_tags=["date", "quiet", "photo_friendly", "indoor"],
                preferred_restaurant_tags=["date", "quiet", "proper_meal", "light_food"],
                avoid_restaurant_tags=["quick_meal"],
                soft_preferences=["仪式感", "低打扰"],
                reasoning=["约会不应只按距离选最近地点，而要突出氛围。"],
            )
        elif "child" in relations:
            self._merge(
                strategy,
                name="family_child_safe_plan",
                summary="亲子场景优先安全、适龄、少换乘且可休息的活动。",
                activity_focus=["亲子场馆", "游乐场", "公园", "博物馆"],
                restaurant_focus=["可容纳家庭", "正餐", "少排队"],
                preferred_activity_tags=["kid_friendly", "child_safe", "outdoor", "indoor"],
                preferred_restaurant_tags=["group_table", "proper_meal", "kid_friendly"],
                hard_constraints=["活动需适龄且安全"],
                soft_preferences=["减少换乘", "控制步行"],
                reasoning=["孩子同行时安全和节奏比纯距离更重要。"],
            )
        elif "friend_group" in relations or "colleague" in relations:
            self._merge(
                strategy,
                name="group_social_plan",
                summary="多人场景优先空间容量、参与感和交通公平。",
                activity_focus=["商场", "桌游/工坊", "运动中心", "团队活动"],
                restaurant_focus=["多人桌", "预算稳定", "交通方便"],
                preferred_activity_tags=["group_friendly", "team_building", "indoor", "transit_accessible"],
                preferred_restaurant_tags=["group_table", "proper_meal", "budget_control"],
                soft_preferences=["多人参与感", "集合方便"],
                reasoning=["多人方案不能只挑最近小店，要考虑容量和集合成本。"],
            )

        strategy.preferred_activity_tags = unique_strings(strategy.preferred_activity_tags)
        strategy.preferred_restaurant_tags = unique_strings(strategy.preferred_restaurant_tags)
        strategy.avoid_activity_categories = unique_strings(strategy.avoid_activity_categories)
        strategy.avoid_restaurant_tags = unique_strings(strategy.avoid_restaurant_tags)
        strategy.hard_constraints = unique_strings(strategy.hard_constraints)
        strategy.soft_preferences = unique_strings(strategy.soft_preferences)
        strategy.search_keywords = unique_strings(strategy.search_keywords)
        strategy.reasoning = unique_strings(strategy.reasoning)
        return strategy

    def _merge(
        self,
        strategy: PlanningStrategy,
        *,
        name: str,
        summary: str,
        activity_focus: list[str],
        restaurant_focus: list[str],
        preferred_activity_tags: list[str],
        preferred_restaurant_tags: list[str],
        avoid_activity_categories: list[str] | None = None,
        avoid_restaurant_tags: list[str] | None = None,
        hard_constraints: list[str] | None = None,
        soft_preferences: list[str] | None = None,
        reasoning: list[str] | None = None,
    ) -> None:
        strategy.name = name
        strategy.summary = summary
        strategy.activity_focus.extend(activity_focus)
        strategy.restaurant_focus.extend(restaurant_focus)
        strategy.preferred_activity_tags.extend(preferred_activity_tags)
        strategy.preferred_restaurant_tags.extend(preferred_restaurant_tags)
        strategy.avoid_activity_categories.extend(avoid_activity_categories or [])
        strategy.avoid_restaurant_tags.extend(avoid_restaurant_tags or [])
        strategy.hard_constraints.extend(hard_constraints or [])
        strategy.soft_preferences.extend(soft_preferences or [])
        strategy.reasoning.extend(reasoning or [])



class LongCatStrategyBuilder:
    """LLM strategy planner used before POI search and scoring."""

    def __init__(self, fallback: PersonaStrategyBuilder, client: LongCatClient) -> None:
        self.fallback = fallback
        self.client = client

    def build(self, intent: PlanningIntent) -> PlanningStrategy:
        fallback_strategy = self.fallback.build(intent)
        if not self.client.is_configured:
            return fallback_strategy

        try:
            content = self.client.chat(
                [
                    {
                        "role": "system",
                        "content": "你是 NearNow 的本地生活策略规划器。只输出 JSON，不要解释。",
                    },
                    {"role": "user", "content": self._prompt(intent, fallback_strategy)},
                ],
                max_tokens=1200,
                temperature=0.2,
            )
            return self._merge_strategy(fallback_strategy, loads_json(content, "strategy"))
        except LongCatAPIError:
            return fallback_strategy
        except (TypeError, ValueError, KeyError):
            return fallback_strategy

    def _prompt(self, intent: PlanningIntent, fallback_strategy: PlanningStrategy) -> str:
        return json.dumps(
            {
                "task": "根据用户画像和目标，制定 POI 搜索与排序策略。不要编造店名，只分析应该找什么类型的真实地点。",
                "intent": {
                    "message": intent.message,
                    "participants": to_plain(intent.participants),
                    "preferences": intent.preferences,
                    "scenario_tags": intent.scenario_tags,
                    "party_size": intent.party_size,
                    "radius_km": intent.radius_km,
                    "start_time": intent.start_time,
                    "end_time": intent.end_time,
                },
                "fallback_strategy": to_plain(fallback_strategy),
                "rules": [
                    "输出策略，不输出具体不存在的商家。",
                    "老人走走应优先公园、花园、商场慢逛和清淡正餐，不要把咖啡当晚饭。",
                    "宠物场景活动必须宠物友好，餐厅需明确可携宠或具备户外座位线索并提醒确认。",
                    "儿童场景优先安全、适龄、少换乘。",
                    "闺蜜/恋人/朋友/同事要分别考虑聊天、氛围、容量和交通公平。",
                ],
                "output_schema": {
                    "name": "short_strategy_id",
                    "summary": "一句话策略",
                    "activity_focus": ["公园散步", "商场慢逛"],
                    "restaurant_focus": ["清淡正餐", "少排队"],
                    "preferred_activity_tags": ["stroll_friendly", "low_walking"],
                    "preferred_restaurant_tags": ["proper_meal", "light_food"],
                    "avoid_activity_categories": ["amenity:library"],
                    "avoid_restaurant_tags": ["beverage_only", "heavy_food"],
                    "hard_constraints": ["避免长距离步行"],
                    "soft_preferences": ["安静", "可休息"],
                    "search_keywords": ["公园", "商场", "清淡"],
                    "reasoning": ["为什么这样规划"],
                },
            },
            ensure_ascii=False,
        )

    def _merge_strategy(self, fallback: PlanningStrategy, data: dict[str, Any]) -> PlanningStrategy:
        return PlanningStrategy(
            name=self._string(data.get("name")) or fallback.name,
            summary=self._string(data.get("summary")) or fallback.summary,
            activity_focus=self._merged(fallback.activity_focus, data.get("activity_focus")),
            restaurant_focus=self._merged(fallback.restaurant_focus, data.get("restaurant_focus")),
            preferred_activity_tags=self._merged(fallback.preferred_activity_tags, data.get("preferred_activity_tags")),
            preferred_restaurant_tags=self._merged(
                fallback.preferred_restaurant_tags,
                data.get("preferred_restaurant_tags"),
            ),
            avoid_activity_categories=self._merged(
                fallback.avoid_activity_categories,
                data.get("avoid_activity_categories"),
            ),
            avoid_restaurant_tags=self._merged(fallback.avoid_restaurant_tags, data.get("avoid_restaurant_tags")),
            hard_constraints=self._merged(fallback.hard_constraints, data.get("hard_constraints")),
            soft_preferences=self._merged(fallback.soft_preferences, data.get("soft_preferences")),
            search_keywords=self._merged(fallback.search_keywords, data.get("search_keywords")),
            reasoning=self._merged(fallback.reasoning, data.get("reasoning")),
        )

    def _merged(self, fallback: list[str], values: Any) -> list[str]:
        result: list[str] = []
        for value in [*fallback, *self._string_list(values)]:
            if value and value not in result:
                result.append(value)
        return result

    def _string_list(self, values: Any) -> list[str]:
        if not isinstance(values, list):
            return []
        return [item for item in (self._string(value) for value in values) if item]

    def _string(self, value: Any) -> str:
        return " ".join(str(value or "").split())
