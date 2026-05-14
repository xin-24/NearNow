from __future__ import annotations

import os

from app.agent.candidate_selector import LongCatCandidateSelector
from app.agent.context_builder import ContextBuilder, PlanningContext
from app.agent.executor import ExecutionManager
from app.agent.intent_parser import IntentParser
from app.agent.longcat_intent_parser import LongCatIntentParser
from app.agent.longcat_response_generator import LongCatResponseGenerator
from app.agent.participant_constraints import ParticipantConstraintBuilder
from app.agent.planner import PlanningEngine
from app.agent.response_generator import ResponseGenerator
from app.agent.strategy import LongCatStrategyBuilder, PersonaStrategyBuilder
from app.domain.enums import RunMode
from app.domain.models import ExecutionResult, Plan
from app.providers.base import LocalLifeProvider, ProviderAPIError
from app.providers.longcat_client import LongCatAPIError, LongCatClient
from app.providers.location_provider import OpenStreetMapLocationProvider
from app.providers.mock_provider import MockLocalLifeProvider
from app.providers.real_provider import OpenStreetMapLocalLifeProvider
from app.utils.time_utils import add_minutes


class PlanStore:
    def __init__(self) -> None:
        self._plans: dict[str, Plan] = {}
        self._modes: dict[str, str] = {}

    def save(self, plan: Plan, mode: str) -> None:
        self._plans[plan.plan_id] = plan
        self._modes[plan.plan_id] = mode

    def get(self, plan_id: str) -> Plan | None:
        return self._plans.get(plan_id)

    def get_mode(self, plan_id: str) -> str | None:
        return self._modes.get(plan_id)


class LocalPlannerAgent:
    def __init__(self, llm_client: LongCatClient | None = None, default_mode: str | None = None) -> None:
        self.default_mode = default_mode or os.getenv("NEARNOW_PROVIDER_MODE", RunMode.REAL.value)
        self.mock_provider = MockLocalLifeProvider()
        self.real_provider = OpenStreetMapLocalLifeProvider()
        self.location_provider = OpenStreetMapLocationProvider()
        self.provider = self._provider_for_mode(self.default_mode)
        self.llm_client = llm_client or LongCatClient.from_env()
        fallback_parser = IntentParser()
        fallback_response_generator = ResponseGenerator()
        self.parser = LongCatIntentParser(fallback_parser, self.llm_client)
        self.constraint_builder = ParticipantConstraintBuilder()
        self.strategy_builder = LongCatStrategyBuilder(PersonaStrategyBuilder(), self.llm_client)
        self.candidate_selector = LongCatCandidateSelector(self.llm_client)
        self.context_builder = ContextBuilder()
        self.planner = PlanningEngine(self.provider)
        self.executor = ExecutionManager(self.provider)
        self.response_generator = LongCatResponseGenerator(fallback_response_generator, self.llm_client)
        self.store = PlanStore()

    def plan(self, payload: dict) -> dict:
        message = payload.get("message", "").strip()
        if not message:
            return self._error("EMPTY_MESSAGE", "请输入一句活动目标。", True)
        mode = self._normalize_mode(payload.get("mode"))
        explicit_participants = self._explicit_participants(payload)

        try:
            intent = self.parser.parse(message, explicit_participants)
        except LongCatAPIError as exc:
            return self._longcat_error(exc)

        intent = self.constraint_builder.normalize(intent)
        try:
            strategy = self.strategy_builder.build(intent)
        except LongCatAPIError as exc:
            return self._longcat_error(exc)

        user_context_payload = self._prepare_user_context(payload.get("user_context"), mode)
        if isinstance(user_context_payload, dict) and "error" in user_context_payload:
            return user_context_payload["error"]

        context = self.context_builder.build(intent, user_context_payload, strategy)
        if isinstance(context, dict):
            return self._error(context["code"], context["message"], context["recoverable"])

        provider = self._provider_for_mode(mode)
        planner = PlanningEngine(provider, self.candidate_selector)
        try:
            plan = planner.generate_plan(context)
        except ProviderAPIError as exc:
            return self._provider_error(exc)
        except LongCatAPIError as exc:
            return self._longcat_error(exc)

        try:
            plan.final_message = self.response_generator.summarize_plan(plan)
        except LongCatAPIError as exc:
            return self._longcat_error(exc)

        self.store.save(plan, mode)
        return {"success": True, "data": plan.to_dict(), "error": None}

    def confirm(self, payload: dict) -> dict:
        plan_id = payload.get("plan_id")
        plan = self.store.get(plan_id)
        if not plan:
            return self._error("PLAN_NOT_FOUND", "找不到这个方案，请重新生成计划。", False)
        selected_route_mode = payload.get("selected_route_mode")
        if selected_route_mode and not self._apply_selected_route(plan, str(selected_route_mode)):
            return self._error("ROUTE_NOT_FOUND", "找不到选择的交通方式，请重新生成方案。", True)
        action_ids = payload.get("confirmed_action_ids")
        provider = self._provider_for_mode(self.store.get_mode(plan_id) or self.default_mode)
        result: ExecutionResult = ExecutionManager(provider).execute(plan, action_ids)
        return {"success": True, "data": result.to_dict(), "error": None}

    def _apply_selected_route(self, plan: Plan, selected_route_mode: str) -> bool:
        route = next((item for item in plan.route_options if item.mode == selected_route_mode), None)
        if route is None:
            return False

        current_route = next((item for item in plan.route_options if item.selected), None)
        current_duration = current_route.duration_minutes if current_route else route.duration_minutes
        for item in plan.route_options:
            item.selected = item.mode == route.mode

        if not plan.schedule:
            return True

        travel_index = next((index for index, item in enumerate(plan.schedule) if item.type == "travel"), None)
        if travel_index is None:
            return True

        travel = plan.schedule[travel_index]
        current_duration = travel.travel_minutes or current_duration
        delta_minutes = route.duration_minutes - current_duration

        travel.end_time = add_minutes(travel.start_time, route.duration_minutes)
        travel.travel_minutes = route.duration_minutes
        travel.transport_mode = route.mode
        travel.reason = self._route_reason(route.mode)

        if delta_minutes:
            for item in plan.schedule[travel_index + 1 :]:
                item.start_time = add_minutes(item.start_time, delta_minutes)
                item.end_time = add_minutes(item.end_time, delta_minutes)

        self._sync_pending_action_times(plan)
        return True

    def _sync_pending_action_times(self, plan: Plan) -> None:
        activity = next((item for item in plan.schedule if item.type == "activity"), None)
        restaurant = next((item for item in plan.schedule if item.type == "restaurant"), None)
        for action in plan.pending_actions:
            if action.type == "book_activity" and activity:
                action.payload["start_time"] = activity.start_time
            if action.type == "reserve_restaurant" and restaurant:
                action.payload["arrival_time"] = restaurant.start_time

    def _route_reason(self, mode: str) -> str:
        if mode == "driving":
            return "已按你的选择改为驾车，适合多人同行和减少步行。"
        if mode == "ride_hailing":
            return "已按你的选择改为网约车，减少换乘和停车成本。"
        if mode == "public_transit":
            return "已按你的选择改为公交/地铁，成本更低，适合多人统一出行。"
        if mode == "walking":
            return "已按你的选择改为步行，适合距离较近、节奏更松的安排。"
        if mode == "cycling":
            return "已按你的选择改为骑行，适合轻量出行并控制成本。"
        return "已按你的选择更新交通方式。"

    def _prepare_user_context(self, user_context: dict | None, mode: str) -> dict | None:
        if mode == RunMode.MOCK.value or not isinstance(user_context, dict):
            return user_context
        if user_context.get("location_source") != "manual" or not user_context.get("home_location"):
            return user_context

        enriched = dict(user_context)
        try:
            address = self.location_provider.geocode(
                str(user_context["home_location"]),
                city=user_context.get("city"),
                district=user_context.get("district"),
                landmark=user_context.get("landmark"),
            )
        except RuntimeError:
            return {
                "error": self._error(
                    "GEOCODE_FAILED",
                    "手动位置无法完成真实地理编码，请补充城市、区县和商圈/地标后重试。",
                    True,
                )
            }
        if address.coordinates is None:
            return {
                "error": self._error(
                    "GEOCODE_FAILED",
                    "手动位置没有返回可用坐标，请换一个更明确的城市、区县和地标。",
                    True,
                )
            }

        enriched["coordinates"] = {"lat": address.coordinates.lat, "lng": address.coordinates.lng}
        enriched["home_location"] = address.formatted_address or enriched["home_location"]
        enriched["city"] = address.city or enriched.get("city")
        enriched["district"] = address.district
        enriched["landmark"] = address.landmark
        enriched["formatted_address"] = address.formatted_address
        enriched["address_source"] = address.source
        enriched["address_confidence"] = address.confidence
        return enriched

    def _normalize_mode(self, raw_mode: object | None) -> str:
        mode = str(raw_mode or self.default_mode).strip().lower()
        if mode == RunMode.MOCK.value:
            return RunMode.MOCK.value
        return RunMode.REAL.value

    def _explicit_participants(self, payload: dict) -> list[dict] | None:
        participants = payload.get("participants")
        if isinstance(participants, list) and participants:
            return participants
        companions = payload.get("companions")
        if isinstance(companions, list) and companions:
            return [
                {
                    "id": item.get("id") or item.get("name") or f"companion_{index + 1}",
                    "name": item.get("name"),
                    "relation": item.get("relation") or "companion",
                    "count": item.get("count") or 1,
                    "constraints": item.get("constraints") or [],
                }
                for index, item in enumerate(companions)
                if isinstance(item, dict) and (item.get("name") or item.get("relation"))
            ]
        return None

    def _provider_for_mode(self, mode: str) -> LocalLifeProvider:
        if mode == RunMode.MOCK.value:
            return self.mock_provider
        return self.real_provider

    def _error(self, code: str, message: str, recoverable: bool) -> dict:
        return {
            "success": False,
            "data": None,
            "error": {"code": code, "message": message, "recoverable": recoverable},
        }

    def _longcat_error(self, error: LongCatAPIError) -> dict:
        message = str(error)
        if "LONGCAT_API_KEY" in message:
            return self._error(
                "LONGCAT_API_NOT_CONFIGURED",
                "LongCat API Key 未配置，无法调用真实模型生成方案。",
                True,
            )
        return self._error(
            "LONGCAT_API_ERROR",
            "LongCat API 调用失败，请稍后重试或检查模型服务配置。",
            True,
        )

    def _provider_error(self, error: ProviderAPIError) -> dict:
        return self._error(
            "REAL_PROVIDER_ERROR",
            str(error) or "真实位置、店铺或路线服务调用失败。",
            True,
        )
