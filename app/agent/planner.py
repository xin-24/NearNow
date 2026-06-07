from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace

from app.agent.candidate_selector import CandidateDecision, CandidateTuple, LongCatCandidateSelector
from app.agent.context_builder import PlanningContext
from app.agent.persona_query import CandidateQualityGate, CandidateQualityReport, PersonaQueryPlanner, PersonaSearchProfile
from app.domain.models import (
    Activity,
    PendingAction,
    Plan,
    Restaurant,
    RouteOption,
    ScheduleItem,
)
from app.providers.base import LocalLifeProvider, ProviderAPIError
from app.providers.longcat_client import LongCatAPIError
from app.providers.meituan_link import HandoffLinkBuilder
from app.utils.geo import distance_km
from app.utils.ids import next_action_id, next_plan_id
from app.utils.time_utils import add_minutes


MAX_ROUTE_ACTIVITY_CANDIDATES = 8
MAX_RESTAURANT_CANDIDATES = 12
MAX_SELECTOR_CANDIDATES = 8
MAX_ROUTE_WORKERS = 4
REAL_MAP_PROVIDERS = {"osm_overpass", "amap"}

MEAL_BUDGET_MINUTES = 45
AVG_ACTIVITY_MINUTES = 80
AVG_TRAVEL_MINUTES = 12
MAX_CHAIN_LENGTH = 3
MIN_PLAN_DURATION_MINUTES = 240
MAX_PLAN_DURATION_MINUTES = 360
DEFAULT_RESTAURANT_MINUTES = 50
MAX_RESTAURANT_MINUTES = 90


@dataclass(frozen=True)
class CandidateScoreParts:
    activity: float
    restaurant: float
    route: float
    pair: float
    proximity: float


@dataclass(frozen=True)
class CandidateScoringProfile:
    key: str
    label: str
    description: str
    activity_weight: float
    restaurant_weight: float
    route_weight: float
    pair_weight: float
    proximity_weight: float = 0


BALANCED_PROFILE = CandidateScoringProfile(
    key="balanced",
    label="综合推荐",
    description="画像匹配、距离、交通和餐饮体验均衡。",
    activity_weight=1,
    restaurant_weight=1,
    route_weight=1,
    pair_weight=1,
)

ALTERNATIVE_SCORING_PROFILES = [
    CandidateScoringProfile(
        key="place_first",
        label="地点优先",
        description="更看重地点和餐厅是否贴合人物画像，允许稍微多移动。",
        activity_weight=1.45,
        restaurant_weight=1.35,
        route_weight=0.65,
        pair_weight=0.65,
        proximity_weight=0.2,
    ),
    CandidateScoringProfile(
        key="distance_first",
        label="距离优先",
        description="更看重少移动、近距离和动线顺畅，体验匹配适当让位。",
        activity_weight=0.65,
        restaurant_weight=0.75,
        route_weight=1.45,
        pair_weight=1.65,
        proximity_weight=2.2,
    ),
]


class PlanningEngine:
    def __init__(
        self,
        provider: LocalLifeProvider,
        candidate_selector: LongCatCandidateSelector | None = None,
        meituan_links: HandoffLinkBuilder | None = None,
    ) -> None:
        self.provider = provider
        self.candidate_selector = candidate_selector
        self.meituan_links = meituan_links or HandoffLinkBuilder()
        self.query_planner = PersonaQueryPlanner()
        self.quality_gate = CandidateQualityGate()

    def generate_plan(self, context: PlanningContext) -> Plan:
        intent = context.intent
        search_profile = self.query_planner.build(context)
        search_tags = self._search_tags(context, search_profile)
        activities, restaurants, search_radius_km, expanded_radius_km = self._search_candidates(
            context,
            search_tags,
            search_profile,
        )
        activities = self._rank_activity_candidates(activities, context)[:MAX_ROUTE_ACTIVITY_CANDIDATES]
        restaurants = self._rank_restaurant_candidates(restaurants, context)[:MAX_RESTAURANT_CANDIDATES]
        quality_report = self.quality_gate.evaluate(
            context,
            activities,
            restaurants,
            self._activity_targets(context),
            self._restaurant_targets(context),
            search_profile,
            expanded_radius_km,
        )

        candidates: list[CandidateTuple] = []
        modes = self._allowed_transport_modes(intent.scenario_tags)
        for activity, routes in self._routes_for_activities(activities, context, modes):
            selected_route = self._select_route(routes, context)
            for restaurant in restaurants:
                if not self._satisfies_restaurant_hard_constraints(restaurant, context):
                    continue
                score = self._weighted_candidate_score(
                    activity,
                    restaurant,
                    selected_route,
                    context,
                    BALANCED_PROFILE,
                )
                candidates.append((score, activity, restaurant, selected_route, routes))

        if not candidates:
            return self._fallback_plan(context, activities, restaurants, quality_report)

        candidates.sort(key=lambda item: item[0], reverse=True)

        budget_minutes = self._time_budget_minutes(context)
        chain = self._select_activity_chain(activities, context, budget_minutes)
        if not chain:
            chain = [candidates[0][1]]

        restaurant = self._select_restaurant_for_chain(restaurants, chain[-1], context)
        if not restaurant:
            restaurant = candidates[0][2]

        first_activity = chain[0]
        first_activity_routes: list[RouteOption] = []
        for candidate in candidates:
            if candidate[1].activity_id == first_activity.activity_id:
                first_activity_routes = candidate[4]
                break
        if not first_activity_routes:
            try:
                first_activity_routes = self.provider.calculate_routes(
                    context.origin_name,
                    context.origin_coordinates,
                    first_activity.name,
                    first_activity.coordinates,
                    modes,
                )
            except ProviderAPIError:
                return self._fallback_plan(context, activities, restaurants, quality_report)
        if not first_activity_routes:
            return self._fallback_plan(context, activities, restaurants, quality_report)
        origin_route = self._select_route(first_activity_routes, context)
        for route in first_activity_routes:
            route.selected = route is origin_route

        inter_routes = self._routes_between_chain(chain, context, modes)

        selected_candidate = candidates[0]
        selection_reasoning: list[str] = []
        if self.candidate_selector is not None and len(candidates) > 1:
            try:
                selector_candidates = self._candidate_selection_pool(candidates, MAX_SELECTOR_CANDIDATES)
                decision = self.candidate_selector.decide(context, selector_candidates)
                selected_candidate = self._candidate_from_decision(decision, selector_candidates)
                selection_reasoning = decision.reasoning
            except LongCatAPIError:
                pass

        alternatives = self._weighted_alternatives(
            candidates,
            selected_candidate,
            context,
            quality_report,
            search_radius_km,
        )
        return self._build_plan(
            context,
            chain,
            restaurant,
            origin_route,
            first_activity_routes,
            inter_routes,
            alternatives,
            selection_reasoning,
            quality_report,
            search_radius_km,
        )

    def _search_candidates(
        self,
        context: PlanningContext,
        search_tags: list[str],
        profile: PersonaSearchProfile,
    ) -> tuple[list[Activity], list[Restaurant], float, float | None]:
        intent = context.intent
        activities, restaurants = self._search_candidate_pair(context, search_tags, intent.radius_km)

        if not self.quality_gate.needs_expansion(
            activities,
            restaurants,
            self._activity_targets(context),
            self._restaurant_targets(context),
            profile,
        ):
            return activities, restaurants, intent.radius_km, None

        expanded_radius = min(profile.max_radius_km, max(intent.radius_km + 2, intent.radius_km * profile.expansion_factor))
        if expanded_radius <= intent.radius_km:
            return activities, restaurants, intent.radius_km, None

        expanded_activities, expanded_restaurants = self._search_candidate_pair(context, search_tags, expanded_radius)
        return (
            self._merge_activities(activities, expanded_activities),
            self._merge_restaurants(restaurants, expanded_restaurants),
            expanded_radius,
            expanded_radius,
        )

    def _search_candidate_pair(
        self,
        context: PlanningContext,
        search_tags: list[str],
        radius_km: float,
    ) -> tuple[list[Activity], list[Restaurant]]:
        intent = context.intent
        with ThreadPoolExecutor(max_workers=2) as executor:
            activity_future = executor.submit(
                self.provider.search_activities,
                search_tags,
                intent.party_size,
                radius_km,
                context.origin_coordinates,
            )
            restaurant_future = executor.submit(
                self.provider.search_restaurants,
                search_tags,
                intent.party_size,
                radius_km,
                context.origin_coordinates,
            )
            return activity_future.result(), restaurant_future.result()

    def _merge_activities(self, first: list[Activity], second: list[Activity]) -> list[Activity]:
        result: list[Activity] = []
        seen: set[str] = set()
        for item in [*first, *second]:
            if item.activity_id in seen:
                continue
            seen.add(item.activity_id)
            result.append(item)
        return result

    def _merge_restaurants(self, first: list[Restaurant], second: list[Restaurant]) -> list[Restaurant]:
        result: list[Restaurant] = []
        seen: set[str] = set()
        for item in [*first, *second]:
            if item.restaurant_id in seen:
                continue
            seen.add(item.restaurant_id)
            result.append(item)
        return result

    def _time_budget_minutes(self, context: PlanningContext) -> int:
        from datetime import datetime
        start = datetime.strptime(context.intent.start_time, "%H:%M")
        end = datetime.strptime(context.intent.end_time, "%H:%M")
        delta = (end - start).total_seconds() / 60
        return max(120, min(int(delta), 480))

    def _target_plan_duration_minutes(self, context: PlanningContext) -> int:
        budget = min(self._time_budget_minutes(context), MAX_PLAN_DURATION_MINUTES)
        if budget < MIN_PLAN_DURATION_MINUTES:
            return budget
        return MIN_PLAN_DURATION_MINUTES

    def _duration_between(self, start_time: str, end_time: str) -> int:
        start = self._minutes_since_midnight(start_time)
        end = self._minutes_since_midnight(end_time)
        delta = end - start
        if delta < 0:
            delta += 24 * 60
        return delta

    def _minutes_since_midnight(self, time_text: str) -> int:
        hour, minute = str(time_text or "00:00").split(":", 1)
        return int(hour) * 60 + int(minute)

    def _target_activity_count(self, budget_minutes: int) -> int:
        remaining = budget_minutes - MEAL_BUDGET_MINUTES
        count = 0
        while remaining >= AVG_ACTIVITY_MINUTES + AVG_TRAVEL_MINUTES and count < MAX_CHAIN_LENGTH:
            remaining -= AVG_ACTIVITY_MINUTES + AVG_TRAVEL_MINUTES
            count += 1
        return max(1, count)

    def _select_activity_chain(
        self,
        activities: list[Activity],
        context: PlanningContext,
        budget_minutes: int,
    ) -> list[Activity]:
        if not activities:
            return []
        target = self._target_activity_count(budget_minutes)
        eligible = [a for a in activities if self._satisfies_activity_hard_constraints(a, context)]
        if not eligible:
            return []

        scored = sorted(
            eligible,
            key=lambda a: self._activity_score(a, context),
            reverse=True,
        )

        chain: list[Activity] = [scored[0]]
        used_ids = {scored[0].activity_id}

        for _ in range(target - 1):
            best: Activity | None = None
            best_score = -9999.0
            for candidate in scored:
                if candidate.activity_id in used_ids:
                    continue
                base_score = self._activity_score(candidate, context)
                prox = max(0, 10 - distance_km(chain[-1].coordinates, candidate.coordinates))
                combined = base_score + prox * 1.5
                est_inter_travel = max(5, round(distance_km(chain[-1].coordinates, candidate.coordinates) * 5))
                accumulated = sum(a.duration_minutes for a in chain) + est_inter_travel
                remaining_travel_est = max(5, round(candidate.distance_km * 4))
                if accumulated + candidate.duration_minutes + remaining_travel_est + MEAL_BUDGET_MINUTES > budget_minutes:
                    continue
                if combined > best_score:
                    best_score = combined
                    best = candidate
            if best is None:
                break
            chain.append(best)
            used_ids.add(best.activity_id)

        return chain

    def _select_restaurant_for_chain(
        self,
        restaurants: list[Restaurant],
        last_activity: Activity,
        context: PlanningContext,
    ) -> Restaurant | None:
        eligible = [r for r in restaurants if self._satisfies_restaurant_hard_constraints(r, context)]
        if not eligible:
            return None

        def combined_score(r: Restaurant) -> float:
            quality = self._restaurant_score(r, context)
            prox = max(0, 10 - distance_km(last_activity.coordinates, r.coordinates))
            return quality + prox * 1.5

        return max(eligible, key=combined_score)

    def _routes_between_chain(
        self,
        chain: list[Activity],
        context: PlanningContext,
        modes: list[str],
    ) -> list[RouteOption]:
        if len(chain) < 2:
            return []
        inter_routes: list[RouteOption] = []
        for i in range(len(chain) - 1):
            try:
                routes = self.provider.calculate_routes(
                    chain[i].name,
                    chain[i].coordinates,
                    chain[i + 1].name,
                    chain[i + 1].coordinates,
                    modes,
                )
                if routes:
                    inter_routes.append(self._select_route(routes, context))
                else:
                    inter_routes.append(self._fallback_route(chain[i], chain[i + 1]))
            except ProviderAPIError:
                inter_routes.append(self._fallback_route(chain[i], chain[i + 1]))
        return inter_routes

    def _fallback_route(self, origin_activity: Activity, dest_activity: Activity) -> RouteOption:
        dist = distance_km(origin_activity.coordinates, dest_activity.coordinates)
        return RouteOption(
            from_name=origin_activity.name,
            to_name=dest_activity.name,
            mode="driving",
            duration_minutes=max(5, round(dist * 4)),
            distance_km=round(dist, 1),
            estimated_cost=15,
            comfort_score=0.8,
            kid_friendly_score=0.7,
            route_geometry=[origin_activity.coordinates, dest_activity.coordinates],
        )

    def _candidate_selection_pool(
        self,
        candidates: list[CandidateTuple],
        limit: int,
    ) -> list[CandidateTuple]:
        selected: list[CandidateTuple] = []
        seen_pairs: set[tuple[str, str]] = set()
        seen_activities: set[str] = set()
        seen_restaurants: set[str] = set()

        def add(candidate: CandidateTuple) -> None:
            activity = candidate[1]
            restaurant = candidate[2]
            pair = (activity.activity_id, restaurant.restaurant_id)
            if pair in seen_pairs or len(selected) >= limit:
                return
            selected.append(candidate)
            seen_pairs.add(pair)
            seen_activities.add(activity.activity_id)
            seen_restaurants.add(restaurant.restaurant_id)

        for candidate in candidates:
            if candidate[1].activity_id not in seen_activities and candidate[2].restaurant_id not in seen_restaurants:
                add(candidate)
        for candidate in candidates:
            if candidate[2].restaurant_id not in seen_restaurants:
                add(candidate)
        for candidate in candidates:
            if candidate[1].activity_id not in seen_activities:
                add(candidate)
        for candidate in candidates:
            add(candidate)
        return selected

    def _alternative_candidates(
        self,
        candidates: list[CandidateTuple],
        selected_candidate: CandidateTuple,
    ) -> list[CandidateTuple]:
        return self._candidate_selection_pool(
            [
                item
                for item in candidates
                if not self._same_candidate_places(item, selected_candidate)
            ],
            3,
        )

    def _weighted_alternatives(
        self,
        candidates: list[CandidateTuple],
        selected_candidate: CandidateTuple,
        context: PlanningContext,
        quality_report: CandidateQualityReport | None = None,
        search_radius_km: float | None = None,
    ) -> list[dict]:
        alternatives: list[dict] = []
        used_pairs = {self._candidate_pair_key(selected_candidate)}
        used_activities = {selected_candidate[1].activity_id}
        used_restaurants = {selected_candidate[2].restaurant_id}

        for profile in ALTERNATIVE_SCORING_PROFILES:
            candidate = self._best_weighted_candidate(
                candidates,
                profile,
                context,
                used_pairs,
                used_activities,
                used_restaurants,
            )
            if candidate is None:
                continue
            used_pairs.add(self._candidate_pair_key(candidate))
            used_activities.add(candidate[1].activity_id)
            used_restaurants.add(candidate[2].restaurant_id)
            alternatives.append(self._alternative_payload(candidate, profile, context, quality_report, search_radius_km))

        if len(alternatives) < len(ALTERNATIVE_SCORING_PROFILES):
            for candidate in self._alternative_candidates(candidates, selected_candidate):
                if len(alternatives) >= len(ALTERNATIVE_SCORING_PROFILES):
                    break
                if self._candidate_pair_key(candidate) in used_pairs:
                    continue
                alternatives.append(self._alternative_payload(candidate, BALANCED_PROFILE, context, quality_report, search_radius_km))
                used_pairs.add(self._candidate_pair_key(candidate))

        return alternatives

    def _best_weighted_candidate(
        self,
        candidates: list[CandidateTuple],
        profile: CandidateScoringProfile,
        context: PlanningContext,
        used_pairs: set[tuple[str, str]],
        used_activities: set[str],
        used_restaurants: set[str],
    ) -> CandidateTuple | None:
        ranked = sorted(
            candidates,
            key=lambda candidate: self._weighted_candidate_score(
                candidate[1],
                candidate[2],
                candidate[3],
                context,
                profile,
            ),
            reverse=True,
        )

        for candidate in ranked:
            if self._candidate_pair_key(candidate) not in used_pairs:
                if candidate[1].activity_id not in used_activities and candidate[2].restaurant_id not in used_restaurants:
                    return candidate
        for candidate in ranked:
            if self._candidate_pair_key(candidate) not in used_pairs:
                if candidate[1].activity_id not in used_activities or candidate[2].restaurant_id not in used_restaurants:
                    return candidate
        for candidate in ranked:
            if self._candidate_pair_key(candidate) not in used_pairs:
                return candidate
        return ranked[0] if ranked else None

    def _candidate_pair_key(self, candidate: CandidateTuple) -> tuple[str, str]:
        return candidate[1].activity_id, candidate[2].restaurant_id

    def _candidate_score_parts(
        self,
        activity: Activity,
        restaurant: Restaurant,
        route: RouteOption,
        context: PlanningContext,
    ) -> CandidateScoreParts:
        pair_distance = distance_km(activity.coordinates, restaurant.coordinates)
        proximity = max(0, 18 - activity.distance_km - restaurant.distance_km - pair_distance)
        return CandidateScoreParts(
            activity=self._activity_score(activity, context),
            restaurant=self._restaurant_score(restaurant, context),
            route=self._route_score(route, context),
            pair=self._pair_score(activity, restaurant, context),
            proximity=proximity,
        )

    def _weighted_candidate_score(
        self,
        activity: Activity,
        restaurant: Restaurant,
        route: RouteOption,
        context: PlanningContext,
        profile: CandidateScoringProfile,
    ) -> float:
        parts = self._candidate_score_parts(activity, restaurant, route, context)
        return (
            parts.activity * profile.activity_weight
            + parts.restaurant * profile.restaurant_weight
            + parts.route * profile.route_weight
            + parts.pair * profile.pair_weight
            + parts.proximity * profile.proximity_weight
        )

    def _alternative_payload(
        self,
        candidate: CandidateTuple,
        profile: CandidateScoringProfile,
        context: PlanningContext,
        quality_report: CandidateQualityReport | None = None,
        search_radius_km: float | None = None,
    ) -> dict:
        _, activity, restaurant, route, _ = candidate
        parts = self._candidate_score_parts(activity, restaurant, route, context)
        score = self._weighted_candidate_score(activity, restaurant, route, context, profile)
        route_options = self._route_options_for_candidate(route, candidate[4])
        selected_route = next((item for item in route_options if item.selected), route_options[0])
        plan = self._build_plan(
            context,
            [activity],
            restaurant,
            selected_route,
            route_options,
            [],
            [],
            [self._alternative_reason(profile, activity, restaurant, route)],
            quality_report,
            search_radius_km,
        )
        plan.title = f"{profile.label}：{activity.name} + {restaurant.name}"
        return {
            "strategy": profile.key,
            "label": profile.label,
            "description": profile.description,
            "title": f"{activity.name} + {restaurant.name}",
            "reason": self._alternative_reason(profile, activity, restaurant, route),
            "tradeoff": self._alternative_tradeoff(profile),
            "activity": {
                "id": activity.activity_id,
                "name": activity.name,
                "category": activity.category,
                "location": activity.location,
                "distance_km": activity.distance_km,
                "tags": activity.tags,
                "provider": activity.provider,
            },
            "restaurant": {
                "id": restaurant.restaurant_id,
                "name": restaurant.name,
                "location": restaurant.location,
                "distance_km": restaurant.distance_km,
                "tags": restaurant.tags,
                "provider": restaurant.provider,
            },
            "route_mode": route.mode,
            "duration_minutes": route.duration_minutes,
            "distance_km": route.distance_km,
            "score": round(score, 2),
            "score_parts": {
                "activity": round(parts.activity, 2),
                "restaurant": round(parts.restaurant, 2),
                "route": round(parts.route, 2),
                "pair": round(parts.pair, 2),
                "proximity": round(parts.proximity, 2),
            },
            "plan": plan,
        }

    def _route_options_for_candidate(self, selected_route: RouteOption, routes: list[RouteOption]) -> list[RouteOption]:
        result = [
            replace(route, selected=route.mode == selected_route.mode, route_geometry=list(route.route_geometry))
            for route in routes
        ]
        if not any(route.selected for route in result) and result:
            result[0].selected = True
        return result

    def _alternative_reason(
        self,
        profile: CandidateScoringProfile,
        activity: Activity,
        restaurant: Restaurant,
        route: RouteOption,
    ) -> str:
        if profile.key == "place_first":
            return f"更偏向地点体验：{activity.name} 和 {restaurant.name} 的标签更贴合当前人物画像。"
        if profile.key == "distance_first":
            return f"更偏向少移动：首段约 {route.duration_minutes} 分钟，活动和餐厅动线更紧凑。"
        return f"作为备选组合，预计首段 {route.duration_minutes} 分钟到达。"

    def _alternative_tradeoff(self, profile: CandidateScoringProfile) -> str:
        if profile.key == "place_first":
            return "可能比最近方案多一点移动时间，但地点匹配度更高。"
        if profile.key == "distance_first":
            return "更省路程和体力，但地点氛围或画像匹配可能略弱。"
        return "在体验和距离之间保持相对均衡。"

    def _build_plan(
        self,
        context: PlanningContext,
        activity_chain: list[Activity],
        restaurant: Restaurant,
        origin_route: RouteOption,
        origin_routes: list[RouteOption],
        inter_routes: list[RouteOption],
        alternatives: list[dict],
        selection_reasoning: list[str] | None = None,
        quality_report: CandidateQualityReport | None = None,
        search_radius_km: float | None = None,
    ) -> Plan:
        intent = context.intent
        start = intent.start_time
        modes = self._allowed_transport_modes(intent.scenario_tags)

        current_time = start
        schedule: list[ScheduleItem] = []
        activity_start_times: dict[str, str] = {}
        arrive_first = add_minutes(current_time, origin_route.duration_minutes)
        schedule.append(
            ScheduleItem(
                start_time=current_time,
                end_time=arrive_first,
                type="travel",
                name=f"从{context.origin_name}出发",
                location=context.origin_name,
                reason=self._transport_reason(origin_route, context),
                travel_minutes=origin_route.duration_minutes,
                transport_mode=origin_route.mode,
                route_geometry=origin_route.route_geometry,
            )
        )
        current_time = arrive_first

        for i, activity in enumerate(activity_chain):
            act_duration = activity.duration_minutes
            activity_start_times[activity.activity_id] = current_time
            act_end = add_minutes(current_time, act_duration)
            schedule.append(
                ScheduleItem(
                    start_time=current_time,
                    end_time=act_end,
                    type="activity",
                    name=activity.name,
                    location=activity.location,
                    reason=self._activity_reason(activity, context),
                    coordinates=activity.coordinates,
                    provider=activity.provider,
                    provider_place_id=activity.provider_place_id,
                )
            )
            current_time = act_end

            if i < len(activity_chain) - 1 and i < len(inter_routes):
                inter_route = inter_routes[i]
                next_arrive = add_minutes(current_time, inter_route.duration_minutes)
                schedule.append(
                    ScheduleItem(
                        start_time=current_time,
                        end_time=next_arrive,
                        type="travel",
                        name=f"前往{activity_chain[i + 1].name}",
                        location=f"{activity.name} → {activity_chain[i + 1].name}",
                        reason=self._inter_activity_transport_reason(inter_route, context),
                        travel_minutes=inter_route.duration_minutes,
                        transport_mode=inter_route.mode,
                        route_geometry=inter_route.route_geometry,
                    )
                )
                current_time = next_arrive

        try:
            restaurant_routes = self.provider.calculate_routes(
                activity_chain[-1].name,
                activity_chain[-1].coordinates,
                restaurant.name,
                restaurant.coordinates,
                modes,
            )
            restaurant_route = self._select_route(restaurant_routes, context) if restaurant_routes else self._fallback_route(activity_chain[-1], restaurant)  # type: ignore[arg-type]
        except ProviderAPIError:
            restaurant_route = self._fallback_route(activity_chain[-1], restaurant)  # type: ignore[arg-type]

        rest_arrive = add_minutes(current_time, restaurant_route.duration_minutes)
        schedule.append(
            ScheduleItem(
                start_time=current_time,
                end_time=rest_arrive,
                type="travel",
                name=f"前往{restaurant.name}",
                location=f"{activity_chain[-1].name} → {restaurant.name}",
                reason=self._meal_transport_reason(restaurant_route, context),
                travel_minutes=restaurant_route.duration_minutes,
                transport_mode=restaurant_route.mode,
                route_geometry=restaurant_route.route_geometry,
            )
        )
        dinner_start = rest_arrive
        target_plan_end = add_minutes(start, self._target_plan_duration_minutes(context))
        dinner_minutes = DEFAULT_RESTAURANT_MINUTES
        base_dinner_end = add_minutes(dinner_start, dinner_minutes)
        extra_needed = self._duration_between(base_dinner_end, target_plan_end)
        if extra_needed and self._duration_between(start, base_dinner_end) < self._target_plan_duration_minutes(context):
            dinner_extra = min(extra_needed, MAX_RESTAURANT_MINUTES - DEFAULT_RESTAURANT_MINUTES)
            dinner_minutes += dinner_extra
        dinner_end = add_minutes(dinner_start, dinner_minutes)
        schedule.append(
            ScheduleItem(
                start_time=dinner_start,
                end_time=dinner_end,
                type="restaurant",
                name=restaurant.name,
                location=restaurant.location,
                reason=self._restaurant_reason(restaurant, context),
                coordinates=restaurant.coordinates,
                provider=restaurant.provider,
                provider_place_id=restaurant.provider_place_id,
            )
        )
        final_end = self._append_duration_padding(schedule, context, restaurant, dinner_end, target_plan_end)

        pending_actions: list[PendingAction] = []
        for activity in activity_chain:
            if activity.reservation_required:
                pending_actions.append(
                    PendingAction(
                        action_id=next_action_id(),
                        type="book_activity",
                        target=activity.name,
                        payload={
                            "activity_id": activity.activity_id,
                            "party_size": intent.party_size,
                            "start_time": activity_start_times.get(activity.activity_id, arrive_first),
                        },
                    )
                )

        if restaurant.reservation_required or self._supports_restaurant_handoff(restaurant):
            payload = {
                "restaurant_id": restaurant.restaurant_id,
                "party_size": intent.party_size,
                "arrival_time": dinner_start,
            }
            if self._supports_restaurant_handoff(restaurant):
                handoff = self.meituan_links.restaurant_search(restaurant, context)
                payload.update(
                    {
                        "handoff_provider": handoff["provider"],
                        "handoff_label": handoff["label"],
                        "handoff_url": handoff["url"],
                        "handoff_links": handoff["links"],
                        "handoff_query": handoff["query"],
                        "handoff_note": handoff["note"],
                    }
                )
            pending_actions.append(
                PendingAction(
                    action_id=next_action_id(),
                    type="reserve_restaurant",
                    target=restaurant.name,
                    payload=payload,
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

        activity_names = " → ".join(a.name for a in activity_chain)
        return Plan(
            plan_id=plan_id,
            title=f"{activity_names} + {restaurant.name}",
            summary=f"{start} 出发，{final_end} 前结束，包含 {len(activity_chain)} 个活动，优先满足{self._scenario_text(context)}，并控制在附近 {search_radius_km or intent.radius_km:g} 公里内。",
            participant_summary=self._participant_summary(context),
            schedule=schedule,
            route_options=origin_routes,
            pending_actions=pending_actions,
            alternatives=alternatives,
            risk_notes=self._risk_notes(context, origin_route, restaurant, quality_report),
            strategy=context.strategy,
            selection_reasoning=selection_reasoning or [],
        )

    def _append_duration_padding(
        self,
        schedule: list[ScheduleItem],
        context: PlanningContext,
        restaurant: Restaurant,
        current_end: str,
        target_end: str,
    ) -> str:
        if not schedule:
            return current_end
        if self._duration_between(schedule[0].start_time, current_end) >= self._target_plan_duration_minutes(context):
            return current_end

        remaining = self._duration_between(current_end, target_end)
        if remaining <= 0:
            return current_end

        schedule.append(
            ScheduleItem(
                start_time=current_end,
                end_time=target_end,
                type="activity",
                name=self._wrap_up_activity_name(context),
                location=restaurant.location,
                reason=self._wrap_up_activity_reason(context, remaining),
                coordinates=restaurant.coordinates,
            )
        )
        return target_end

    def _wrap_up_activity_name(self, context: PlanningContext) -> str:
        tags = set(context.intent.scenario_tags)
        if "child" in tags:
            return "餐后亲子轻逛"
        if "friend_group" in tags:
            return "餐后周边轻逛"
        if "elder" in tags:
            return "餐后短程休息"
        if "pet" in tags:
            return "餐后宠物友好散步"
        return "餐后周边轻逛"

    def _wrap_up_activity_reason(self, context: PlanningContext, minutes: int) -> str:
        if "child" in context.intent.scenario_tags:
            return f"用餐后留出约 {minutes} 分钟在餐厅周边轻松收尾，避免亲子行程太赶。"
        if "elder" in context.intent.scenario_tags:
            return f"用餐后留出约 {minutes} 分钟短程休息，控制步行强度。"
        return f"用餐后留出约 {minutes} 分钟周边轻逛和集合缓冲，让整体方案达到 4 小时。"

    def _fallback_plan(
        self,
        context: PlanningContext,
        activities: list[Activity],
        restaurants: list[Restaurant],
        quality_report: CandidateQualityReport | None = None,
    ) -> Plan:
        plan_id = next_plan_id()
        notes = []
        if not activities:
            notes.append("没有找到满足人数、距离和参与者硬约束的活动。")
        if not restaurants:
            notes.append("没有找到满足人数、距离和餐饮约束的餐厅。")
        if not notes:
            notes.append("候选结果存在冲突，需要放宽距离、人数或特殊约束。")
        if quality_report:
            notes.extend(quality_report.notes)
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
            strategy=context.strategy,
        )

    def _routes_for_activities(
        self,
        activities: list[Activity],
        context: PlanningContext,
        modes: list[str],
    ) -> list[tuple[Activity, list[RouteOption]]]:
        eligible = [
            activity
            for activity in activities
            if self._satisfies_activity_hard_constraints(activity, context)
        ]
        if not eligible:
            return []

        results: list[tuple[int, Activity, list[RouteOption]]] = []
        failures: list[ProviderAPIError] = []
        provider_worker_limit = getattr(self.provider, "max_route_workers", MAX_ROUTE_WORKERS)
        worker_count = min(provider_worker_limit, len(eligible))
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_to_activity = {
                executor.submit(
                    self.provider.calculate_routes,
                    context.origin_name,
                    context.origin_coordinates,
                    activity.name,
                    activity.coordinates,
                    modes,
                ): (index, activity)
                for index, activity in enumerate(eligible)
            }
            for future in as_completed(future_to_activity):
                index, activity = future_to_activity[future]
                try:
                    routes = future.result()
                except ProviderAPIError as exc:
                    failures.append(exc)
                    continue
                if routes:
                    results.append((index, activity, routes))

        if not results and failures:
            raise failures[0]
        results.sort(key=lambda item: item[0])
        return [(activity, routes) for _, activity, routes in results]

    def _candidate_from_decision(
        self,
        decision: CandidateDecision,
        candidates: list[CandidateTuple],
    ) -> CandidateTuple:
        try:
            index = int(decision.option_id.removeprefix("option_")) - 1
        except ValueError as exc:
            raise LongCatAPIError("LongCat candidate option_id was invalid") from exc
        if index < 0 or index >= len(candidates):
            raise LongCatAPIError("LongCat candidate option_id was outside candidate list")

        score, activity, restaurant, _, routes = candidates[index]
        selected_route = next((route for route in routes if route.mode == decision.route_mode), None)
        if selected_route is None:
            raise LongCatAPIError("LongCat candidate route_mode was outside route list")
        return score, activity, restaurant, selected_route, routes

    def _same_candidate_places(self, left: CandidateTuple, right: CandidateTuple) -> bool:
        return left[1].activity_id == right[1].activity_id and left[2].restaurant_id == right[2].restaurant_id

    def _supports_restaurant_handoff(self, restaurant: Restaurant) -> bool:
        return self._is_real_map_provider(restaurant.provider)

    def _is_real_map_provider(self, provider: str | None) -> bool:
        return str(provider or "") in REAL_MAP_PROVIDERS

    def _satisfies_activity_hard_constraints(self, activity: Activity, context: PlanningContext) -> bool:
        tags = set(activity.tags)
        relations = {participant.relation for participant in context.intent.participants}
        if "pet" in relations and "pet_friendly" not in tags:
            return False
        return True

    def _satisfies_restaurant_hard_constraints(self, restaurant: Restaurant, context: PlanningContext) -> bool:
        if restaurant.wait_minutes > 40:
            return False
        return True

    def _activity_score(self, activity: Activity, context: PlanningContext) -> float:
        tags = set(activity.tags)
        target = self._activity_targets(context)
        relations = {participant.relation for participant in context.intent.participants}
        matched_targets = tags & target
        score = len(matched_targets) * 12 + max(0, 10 - activity.distance_km)
        if "child" in relations:
            score += 18 if {"kid_friendly", "child_safe"} & tags else -6
        if "elder" in relations:
            score += 16 if {"low_walking", "elder_friendly", "quiet"} & tags else -5
            if "stroll" in context.intent.scenario_tags:
                if {"stroll_friendly", "low_walking", "outdoor"} & tags:
                    score += 18
                else:
                    score -= 12
                if activity.category in {"amenity:library", "tourism:museum", "tourism:gallery", "amenity:cafe"}:
                    score -= 18
        if "partner" in relations:
            score += 16 if {"date", "quiet", "photo_friendly"} & tags else -4
        if "bestie" in relations:
            score += 16 if {"bestie", "afternoon_tea", "chat_friendly", "photo_friendly"} & tags else -4
        if "friend_group" in relations:
            score += 10 if {"group_friendly", "team_building"} & tags else -2
        if "colleague" in relations:
            score += 14 if {"team_building", "group_friendly", "transit_accessible"} & tags else -4
        if "pet" in relations:
            score += 18 if {"pet_friendly", "outdoor"} & tags else -20
        if context.strategy:
            if activity.category in set(context.strategy.avoid_activity_categories):
                score -= 30
            score += len(tags & set(context.strategy.preferred_activity_tags)) * 10
        return score

    def _restaurant_score(self, restaurant: Restaurant, context: PlanningContext) -> float:
        tags = set(restaurant.tags)
        target = self._restaurant_targets(context)
        wait_score = max(0, 10 - restaurant.wait_minutes / 3)
        price_score = 8 if "budget_control" not in target or restaurant.average_price <= 150 else 2
        relations = {participant.relation for participant in context.intent.participants}
        score = len(tags & target) * 10 + wait_score + price_score
        if "child" in relations:
            score += 8 if {"kid_friendly", "group_table"} & tags else -3
        if "elder" in relations:
            score += 8 if {"elder_friendly", "low_walking", "quiet", "light_food"} & tags else -3
            if "proper_meal" in context.intent.preferences:
                if {"proper_meal", "light_food"} & tags:
                    score += 16
                if "light_food" in tags:
                    score += 14
                if "heavy_food" in tags:
                    score -= 28
                if "beverage_only" in tags:
                    score -= 22
                if "quick_meal" in tags:
                    score -= 10
        if "partner" in relations:
            score += 8 if {"date", "quiet", "light_food"} & tags else -2
        if "bestie" in relations:
            score += 10 if {"bestie", "afternoon_tea", "chat_friendly", "quiet"} & tags else -3
        if "pet" in relations:
            if "pet_friendly" in tags:
                score += 18
            elif {"pet_possible", "outdoor"} & tags:
                score += 10
            elif "takeaway_possible" in tags:
                score += 3
            else:
                score -= 8
        if context.strategy:
            score += len(tags & set(context.strategy.preferred_restaurant_tags)) * 10
            score -= len(tags & set(context.strategy.avoid_restaurant_tags)) * 18
        return score

    def _search_tags(self, context: PlanningContext, profile: PersonaSearchProfile | None = None) -> list[str]:
        tags = [
            *context.intent.scenario_tags,
            *context.intent.preferences,
            *(context.strategy.preferred_activity_tags if context.strategy else []),
            *(context.strategy.preferred_restaurant_tags if context.strategy else []),
            *(context.strategy.search_keywords if context.strategy else []),
            *(profile.activity_tags if profile else []),
            *(profile.restaurant_tags if profile else []),
        ]
        result: list[str] = []
        for tag in tags:
            if tag and tag not in result:
                result.append(tag)
        return result

    def _activity_targets(self, context: PlanningContext) -> set[str]:
        targets = set(context.intent.scenario_tags + context.intent.preferences)
        if context.strategy:
            targets.update(context.strategy.preferred_activity_tags)
        persona_targets = {
            "child": {"kid_friendly", "child_safe", "indoor", "outdoor"},
            "spouse": {"quiet", "low_walking", "light_food", "date"},
            "partner": {"date", "quiet", "photo_friendly", "indoor"},
            "bestie": {"bestie", "afternoon_tea", "chat_friendly", "photo_friendly"},
            "friend_group": {"group_friendly", "team_building", "indoor"},
            "pet": {"pet_friendly", "outdoor", "low_walking"},
            "elder": {"low_walking", "elder_friendly", "quiet"},
            "colleague": {"team_building", "group_friendly", "transit_accessible"},
            "client": {"business", "quiet", "transit_accessible"},
        }
        for participant in context.intent.participants:
            targets.update(persona_targets.get(participant.relation, set()))
            for constraint in participant.constraints:
                if constraint.value:
                    targets.add(constraint.value)
        return targets

    def _restaurant_targets(self, context: PlanningContext) -> set[str]:
        targets = set(context.intent.preferences)
        if context.strategy:
            targets.update(context.strategy.preferred_restaurant_tags)
        persona_targets = {
            "child": {"kid_friendly", "group_table"},
            "spouse": {"quiet", "light_food", "low_calorie"},
            "partner": {"date", "quiet", "light_food"},
            "bestie": {"bestie", "afternoon_tea", "chat_friendly", "quiet"},
            "friend_group": {"group_table", "budget_control"},
            "pet": {"pet_friendly", "pet_possible", "outdoor", "takeaway_possible"},
            "elder": {"elder_friendly", "light_food", "quiet", "low_walking", "proper_meal"},
            "colleague": {"group_table", "budget_control", "transit_accessible"},
            "client": {"quiet", "business"},
        }
        for participant in context.intent.participants:
            targets.update(persona_targets.get(participant.relation, set()))
            for constraint in participant.constraints:
                if constraint.value:
                    targets.add(constraint.value)
        return targets

    def _rank_activity_candidates(self, activities: list[Activity], context: PlanningContext) -> list[Activity]:
        return sorted(
            activities,
            key=lambda activity: (
                not self._satisfies_activity_hard_constraints(activity, context),
                self._strategy_activity_penalty(activity, context),
                -self._activity_score(activity, context),
                activity.distance_km,
            ),
        )

    def _rank_restaurant_candidates(self, restaurants: list[Restaurant], context: PlanningContext) -> list[Restaurant]:
        return sorted(
            restaurants,
            key=lambda restaurant: (
                not self._satisfies_restaurant_hard_constraints(restaurant, context),
                self._strategy_restaurant_penalty(restaurant, context),
                -self._restaurant_score(restaurant, context),
                restaurant.distance_km,
            ),
        )

    def _strategy_activity_penalty(self, activity: Activity, context: PlanningContext) -> int:
        if not context.strategy:
            return 0
        tags = set(activity.tags)
        penalty = 0
        if activity.category in set(context.strategy.avoid_activity_categories):
            penalty += 1
        if not tags & set(context.strategy.preferred_activity_tags):
            penalty += 1
        return penalty

    def _strategy_restaurant_penalty(self, restaurant: Restaurant, context: PlanningContext) -> int:
        if not context.strategy:
            return 0
        tags = set(restaurant.tags)
        penalty = 0
        if tags & set(context.strategy.avoid_restaurant_tags):
            penalty += 1
        if not tags & set(context.strategy.preferred_restaurant_tags):
            penalty += 1
        return penalty

    def _pair_score(self, activity: Activity, restaurant: Restaurant, context: PlanningContext) -> float:
        distance = distance_km(activity.coordinates, restaurant.coordinates)
        relations = {participant.relation for participant in context.intent.participants}
        score = max(0, 8 - distance)
        if {"elder", "pet"} & relations and distance > 2.5:
            score -= 10
        if "elder" in relations and distance <= 1.5:
            score += 4
        return score

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
            "pet": "宠物：活动必须宠物友好，餐厅优先可携宠/户外座位，不确定时按外带兜底",
            "elder": "老人：优先少走路、安静和座位充足",
            "colleague": "同事：优先团建容量、预算和交通公平",
            "client": "客户：优先商务氛围、隐私和交通稳定",
        }
        result: list[str] = []
        seen: set[str] = set()
        for item in context.intent.participants:
            if item.relation not in labels or item.relation in seen:
                continue
            seen.add(item.relation)
            result.append(labels[item.relation])
        return result or ["个人：优先距离、时间和体验平衡"]

    def _scenario_text(self, context: PlanningContext) -> str:
        relations = list(
            dict.fromkeys(item.relation for item in context.intent.participants if item.relation != "self")
        )
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

    def _meal_transport_reason(self, route: RouteOption, context: PlanningContext) -> str:
        relations = {participant.relation for participant in context.intent.participants}
        if route.mode == "walking":
            return f"活动后步行约 {route.duration_minutes} 分钟到餐厅，节奏较轻。"
        if route.mode == "ride_hailing":
            if "elder" in relations:
                return f"活动后网约车约 {route.duration_minutes} 分钟到餐厅，减少长辈步行压力。"
            if "pet" in relations:
                return f"活动后网约车约 {route.duration_minutes} 分钟到餐厅，减少宠物和同行者步行压力。"
            return f"活动后网约车约 {route.duration_minutes} 分钟到餐厅，减少换乘和步行压力。"
        if route.mode == "driving":
            return f"活动后驾车约 {route.duration_minutes} 分钟到餐厅，适合跨商圈移动。"
        if route.mode == "public_transit":
            return f"活动后公共交通约 {route.duration_minutes} 分钟到餐厅，出发前需复查班次。"
        return f"活动后用{route.mode}约 {route.duration_minutes} 分钟到餐厅。"

    def _inter_activity_transport_reason(self, route: RouteOption, context: PlanningContext) -> str:
        if route.mode == "walking":
            return f"步行约 {route.duration_minutes} 分钟到下一个活动点，节奏轻松。"
        if route.mode == "driving":
            return f"驾车约 {route.duration_minutes} 分钟前往下一个活动点。"
        if route.mode == "ride_hailing":
            return f"网约车约 {route.duration_minutes} 分钟前往下一个活动点。"
        return f"约 {route.duration_minutes} 分钟到达下一个活动点。"

    def _activity_reason(self, activity: Activity, context: PlanningContext) -> str:
        if self._is_real_map_provider(activity.provider):
            return f"适合{self._scenario_text(context)}，安排在饭前节奏比较顺。"
        return f"匹配 {self._scenario_text(context)}，并且当前剩余名额可覆盖 {context.intent.party_size} 人。"

    def _restaurant_reason(self, restaurant: Restaurant, context: PlanningContext) -> str:
        if self._is_real_map_provider(restaurant.provider):
            if "pet" in context.intent.scenario_tags and not {"pet_friendly", "pet_possible", "outdoor"} & set(restaurant.tags):
                return "可作为外带/打包候选；带宠堂食前先电话确认。"
            if (
                "pet" in context.intent.scenario_tags
                and "pet_possible" in restaurant.tags
                and "pet_friendly" not in restaurant.tags
            ):
                return "有户外座位等携宠线索；带宠堂食前先电话确认。"
            return f"适合 {context.intent.party_size} 人用餐，和前一站距离合适。"
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

    def _risk_notes(
        self,
        context: PlanningContext,
        route: RouteOption,
        restaurant: Restaurant,
        quality_report: CandidateQualityReport | None = None,
    ) -> list[str]:
        notes = list(quality_report.notes) if quality_report else []
        if route.traffic_risk == "medium":
            notes.append("驾车可能受实时路况影响，出发前建议复查路线。")
        if restaurant.wait_minutes:
            notes.append(f"{restaurant.name} 可能需要等待约 {restaurant.wait_minutes} 分钟。")
        if self._is_real_map_provider(restaurant.provider):
            notes.append("餐厅营业、等位和预订状态建议出发前复查。")
        if "child" in context.intent.scenario_tags:
            notes.append("儿童需求已作为强偏好排序；地点亲子标签不完整时，仍需出发前确认活动适龄性。")
        if "elder" in context.intent.scenario_tags and route.walking_minutes > 10:
            notes.append("老人同行时建议出发前复查步行距离，必要时改用网约车或驾车。")
        if "pet" in context.intent.scenario_tags:
            if "pet_possible" in restaurant.tags and "pet_friendly" not in restaurant.tags:
                notes.append(f"{restaurant.name} 只有户外座位等携宠线索，并非已确认宠物友好；出发前必须电话确认。")
            elif not {"pet_friendly", "pet_possible", "outdoor"} & set(restaurant.tags):
                notes.append(f"{restaurant.name} 未确认可携宠入店；默认按外带/打包方案执行，不建议直接带宠物入店堂食。")
            else:
                notes.append("携宠出行需要到店前再次确认宠物入内规则。")
        return notes
