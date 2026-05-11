from __future__ import annotations

from app.agent.context_builder import PlanningContext
from app.domain.models import (
    Activity,
    PendingAction,
    Plan,
    Restaurant,
    RouteOption,
    ScheduleItem,
)
from app.providers.base import LocalLifeProvider
from app.utils.ids import next_action_id, next_plan_id
from app.utils.time_utils import add_minutes


class PlanningEngine:
    def __init__(self, provider: LocalLifeProvider) -> None:
        self.provider = provider

    def generate_plan(self, context: PlanningContext) -> Plan:
        intent = context.intent
        activities = self.provider.search_activities(intent.scenario_tags, intent.party_size, intent.radius_km)
        restaurants = self.provider.search_restaurants(intent.scenario_tags, intent.party_size, intent.radius_km)

        candidates = []
        modes = self._allowed_transport_modes(intent.scenario_tags)
        for activity in activities:
            if not self._satisfies_activity_hard_constraints(activity, context):
                continue
            routes = self.provider.calculate_routes(
                context.origin_name,
                context.origin_coordinates,
                activity.name,
                activity.coordinates,
                modes,
            )
            selected_route = self._select_route(routes, context)
            for restaurant in restaurants:
                if not self._satisfies_restaurant_hard_constraints(restaurant, context):
                    continue
                score = (
                    self._activity_score(activity, context)
                    + self._restaurant_score(restaurant, context)
                    + self._route_score(selected_route, context)
                )
                candidates.append((score, activity, restaurant, selected_route, routes))

        if not candidates:
            return self._fallback_plan(context, activities, restaurants)

        candidates.sort(key=lambda item: item[0], reverse=True)
        _, activity, restaurant, selected_route, routes = candidates[0]
        for route in routes:
            route.selected = route is selected_route
        return self._build_plan(context, activity, restaurant, selected_route, routes, candidates[1:3])

    def _build_plan(
        self,
        context: PlanningContext,
        activity: Activity,
        restaurant: Restaurant,
        selected_route: RouteOption,
        routes: list[RouteOption],
        alternatives: list[tuple],
    ) -> Plan:
        intent = context.intent
        start = intent.start_time
        arrive = add_minutes(start, selected_route.duration_minutes)
        activity_end = add_minutes(arrive, min(activity.duration_minutes, 90))
        extension_end = add_minutes(activity_end, 45)
        dinner_start = add_minutes(extension_end, 15)
        dinner_end = add_minutes(dinner_start, 50)

        extension = self._extension_for(context, activity)
        schedule = [
            ScheduleItem(
                start_time=start,
                end_time=arrive,
                type="travel",
                name=f"从{context.origin_name}出发",
                location=context.origin_name,
                reason=self._transport_reason(selected_route, context),
                travel_minutes=selected_route.duration_minutes,
                transport_mode=selected_route.mode,
            ),
            ScheduleItem(
                start_time=arrive,
                end_time=activity_end,
                type="activity",
                name=activity.name,
                location=activity.location,
                reason=self._activity_reason(activity, context),
                coordinates=activity.coordinates,
                provider=activity.provider,
                provider_place_id=activity.provider_place_id,
            ),
            ScheduleItem(
                start_time=activity_end,
                end_time=extension_end,
                type="activity",
                name=extension["name"],
                location=activity.location,
                reason=extension["reason"],
                travel_minutes=5,
                transport_mode="walking",
                coordinates=activity.coordinates,
                provider=activity.provider,
                provider_place_id=activity.provider_place_id,
            ),
            ScheduleItem(
                start_time=dinner_start,
                end_time=dinner_end,
                type="restaurant",
                name=restaurant.name,
                location=restaurant.location,
                reason=self._restaurant_reason(restaurant, context),
                travel_minutes=5,
                transport_mode="walking",
                coordinates=restaurant.coordinates,
                provider=restaurant.provider,
                provider_place_id=restaurant.provider_place_id,
            ),
        ]

        pending_actions: list[PendingAction] = []
        if activity.reservation_required:
            pending_actions.append(
                PendingAction(
                    action_id=next_action_id(),
                    type="book_activity",
                    target=activity.name,
                    payload={
                        "activity_id": activity.activity_id,
                        "party_size": intent.party_size,
                        "start_time": arrive,
                    },
                )
            )
        if restaurant.reservation_required:
            pending_actions.append(
                PendingAction(
                    action_id=next_action_id(),
                    type="reserve_restaurant",
                    target=restaurant.name,
                    payload={
                        "restaurant_id": restaurant.restaurant_id,
                        "party_size": intent.party_size,
                        "arrival_time": dinner_start,
                    },
                )
            )
        pending_actions.append(
            PendingAction(
                action_id=next_action_id(),
                type="send_notification",
                target="同行者",
                payload={"content": ""},
            )
        )

        plan_id = next_plan_id()
        for action in pending_actions:
            action.payload["plan_id"] = plan_id

        return Plan(
            plan_id=plan_id,
            title=f"{activity.name} + {restaurant.name}",
            summary=f"{start} 出发，{dinner_end} 前结束，优先满足{self._scenario_text(context)}，并控制在附近 {intent.radius_km:g} 公里内。",
            participant_summary=self._participant_summary(context),
            schedule=schedule,
            route_options=routes,
            pending_actions=pending_actions,
            alternatives=self._alternatives(alternatives),
            risk_notes=self._risk_notes(context, selected_route, restaurant),
        )

    def _fallback_plan(
        self,
        context: PlanningContext,
        activities: list[Activity],
        restaurants: list[Restaurant],
    ) -> Plan:
        plan_id = next_plan_id()
        notes = []
        if not activities:
            notes.append("没有找到满足人数、距离和参与者硬约束的活动。")
        if not restaurants:
            notes.append("没有找到满足人数、距离和餐饮约束的餐厅。")
        if not notes:
            notes.append("候选结果存在冲突，需要放宽距离、人数或特殊约束。")
        return Plan(
            plan_id=plan_id,
            title="需要补充或放宽条件",
            summary="当前条件下无法生成完整可执行方案。",
            participant_summary=self._participant_summary(context),
            schedule=[],
            route_options=[],
            pending_actions=[],
            alternatives=[],
            risk_notes=notes,
            requires_confirmation=False,
            final_message="我没找到同时满足所有硬约束的方案。可以放宽距离、减少参与人数，或允许我换一个活动类型继续规划。",
        )

    def _satisfies_activity_hard_constraints(self, activity: Activity, context: PlanningContext) -> bool:
        tags = set(activity.tags)
        relations = {participant.relation for participant in context.intent.participants}
        if "child" in relations and not {"kid_friendly", "child_safe"} & tags:
            return False
        if "pet" in relations and "pet_friendly" not in tags:
            return False
        if "elder" in relations and not {"low_walking", "elder_friendly", "quiet"} & tags:
            return False
        return True

    def _satisfies_restaurant_hard_constraints(self, restaurant: Restaurant, context: PlanningContext) -> bool:
        tags = set(restaurant.tags)
        relations = {participant.relation for participant in context.intent.participants}
        if "pet" in relations and "pet_friendly" not in tags:
            return False
        if "elder" in relations and not {"elder_friendly", "low_walking", "quiet"} & tags:
            return False
        if restaurant.wait_minutes > 25:
            return False
        return True

    def _activity_score(self, activity: Activity, context: PlanningContext) -> float:
        tags = set(activity.tags)
        target = set(context.intent.scenario_tags)
        return len(tags & target) * 10 + max(0, 10 - activity.distance_km)

    def _restaurant_score(self, restaurant: Restaurant, context: PlanningContext) -> float:
        tags = set(restaurant.tags)
        target = set(context.intent.scenario_tags + context.intent.preferences)
        wait_score = max(0, 10 - restaurant.wait_minutes / 3)
        price_score = 8 if "budget_control" not in target or restaurant.average_price <= 150 else 2
        return len(tags & target) * 10 + wait_score + price_score

    def _route_score(self, route: RouteOption, context: PlanningContext) -> float:
        relations = {participant.relation for participant in context.intent.participants}
        score = route.comfort_score * 20 - route.duration_minutes / 5
        if {"child", "elder", "pet"} & relations and route.mode in {"driving", "ride_hailing"}:
            score += 6
        if "pet" in relations and route.mode == "public_transit":
            score -= 10
        if "elder" in relations and route.walking_minutes > 10:
            score -= 8
        if route.mode == "cycling" and {"child", "elder", "pet"} & relations:
            score -= 12
        return score

    def _select_route(self, routes: list[RouteOption], context: PlanningContext) -> RouteOption:
        return max(routes, key=lambda route: self._route_score(route, context))

    def _allowed_transport_modes(self, tags: list[str]) -> list[str]:
        if "pet" in tags:
            return ["walking", "driving", "ride_hailing"]
        if "elder" in tags:
            return ["driving", "ride_hailing", "public_transit"]
        return ["walking", "driving", "public_transit", "ride_hailing", "cycling"]

    def _participant_summary(self, context: PlanningContext) -> list[str]:
        labels = {
            "child": "儿童：优先安全、适龄活动和少步行",
            "spouse": "伴侣：照顾饮食偏好和舒适度",
            "partner": "恋人：优先约会氛围和低打扰环境",
            "bestie": "闺蜜：优先拍照、下午茶和适合聊天",
            "friend_group": "朋友：优先多人参与感和可聊天空间",
            "pet": "宠物：只选择宠物友好的活动、餐厅和交通方式",
            "elder": "老人：优先少走路、安静和座位充足",
            "colleague": "同事：优先团建容量、预算和交通公平",
            "client": "客户：优先商务氛围、隐私和交通稳定",
        }
        result = [labels[item.relation] for item in context.intent.participants if item.relation in labels]
        return result or ["个人：优先距离、时间和体验平衡"]

    def _scenario_text(self, context: PlanningContext) -> str:
        relations = [item.relation for item in context.intent.participants if item.relation != "self"]
        mapping = {
            "child": "亲子需求",
            "spouse": "家庭舒适度",
            "partner": "约会氛围",
            "bestie": "闺蜜聊天拍照",
            "friend_group": "朋友多人参与",
            "pet": "宠物友好",
            "elder": "老人少走路",
            "colleague": "同事团建",
            "client": "商务接待",
        }
        return "、".join(mapping.get(relation, relation) for relation in relations) or "个人偏好"

    def _transport_reason(self, route: RouteOption, context: PlanningContext) -> str:
        if route.mode == "driving":
            return "驾车更适合当前同行者，耗时稳定，步行少。"
        if route.mode == "ride_hailing":
            return "网约车能减少换乘和步行，适合短时安排。"
        if route.mode == "public_transit":
            return "公共交通成本低，适合交通公平的多人场景。"
        if route.mode == "walking":
            return "距离较近，步行可以减少等待和停车成本。"
        return "该交通方式在时间和成本之间较平衡。"

    def _activity_reason(self, activity: Activity, context: PlanningContext) -> str:
        return f"匹配 {self._scenario_text(context)}，并且当前剩余名额可覆盖 {context.intent.party_size} 人。"

    def _restaurant_reason(self, restaurant: Restaurant, context: PlanningContext) -> str:
        return f"可容纳 {context.intent.party_size} 人，等待约 {restaurant.wait_minutes} 分钟，标签匹配当前餐饮和同行者约束。"

    def _extension_for(self, context: PlanningContext, activity: Activity) -> dict[str, str]:
        tags = set(context.intent.scenario_tags)
        if "pet" in tags:
            return {"name": "宠物友好散步", "reason": "给宠物留出活动和休息时间。"}
        if "bestie" in tags or "photo_friendly" in tags:
            return {"name": "商圈拍照和轻逛", "reason": "饭前留出轻松聊天和拍照时间。"}
        if "partner" in tags or "date" in tags:
            return {"name": "河畔散步", "reason": "节奏轻，不赶场，适合约会氛围。"}
        if "elder" in tags:
            return {"name": "短程休息散步", "reason": "控制步行强度，中间留出休息。"}
        if "colleague" in tags:
            return {"name": "团队合影和咖啡续聊", "reason": "增强团建参与感，便于等位和集合。"}
        return {"name": "周边轻逛", "reason": "饭前安排轻量活动，避免行程过满。"}

    def _risk_notes(self, context: PlanningContext, route: RouteOption, restaurant: Restaurant) -> list[str]:
        notes = []
        if route.traffic_risk == "medium":
            notes.append("驾车可能受实时路况影响，出发前建议复查路线。")
        if restaurant.wait_minutes:
            notes.append(f"{restaurant.name} 可能需要等待约 {restaurant.wait_minutes} 分钟。")
        if "pet" in context.intent.scenario_tags:
            notes.append("携宠出行需要到店前再次确认宠物入内规则。")
        return notes

    def _alternatives(self, alternatives: list[tuple]) -> list[dict]:
        result = []
        for _, activity, restaurant, route, _ in alternatives:
            result.append(
                {
                    "title": f"{activity.name} + {restaurant.name}",
                    "reason": f"备选交通方式 {route.mode}，预计 {route.duration_minutes} 分钟到达。",
                }
            )
        return result

