from __future__ import annotations

from app.agent.context_builder import ContextBuilder, PlanningContext
from app.agent.executor import ExecutionManager
from app.agent.intent_parser import IntentParser
from app.agent.longcat_intent_parser import LongCatIntentParser
from app.agent.longcat_response_generator import LongCatResponseGenerator
from app.agent.participant_constraints import ParticipantConstraintBuilder
from app.agent.planner import PlanningEngine
from app.agent.response_generator import ResponseGenerator
from app.domain.models import ExecutionResult, Plan
from app.providers.longcat_client import LongCatAPIError, LongCatClient
from app.providers.mock_provider import MockLocalLifeProvider


class PlanStore:
    def __init__(self) -> None:
        self._plans: dict[str, Plan] = {}

    def save(self, plan: Plan) -> None:
        self._plans[plan.plan_id] = plan

    def get(self, plan_id: str) -> Plan | None:
        return self._plans.get(plan_id)


class LocalPlannerAgent:
    def __init__(self, llm_client: LongCatClient | None = None) -> None:
        self.provider = MockLocalLifeProvider()
        self.llm_client = llm_client or LongCatClient.from_env()
        fallback_parser = IntentParser()
        fallback_response_generator = ResponseGenerator()
        self.parser = LongCatIntentParser(fallback_parser, self.llm_client)
        self.constraint_builder = ParticipantConstraintBuilder()
        self.context_builder = ContextBuilder()
        self.planner = PlanningEngine(self.provider)
        self.executor = ExecutionManager(self.provider)
        self.response_generator = LongCatResponseGenerator(fallback_response_generator, self.llm_client)
        self.store = PlanStore()

    def plan(self, payload: dict) -> dict:
        message = payload.get("message", "").strip()
        if not message:
            return self._error("EMPTY_MESSAGE", "请输入一句活动目标。", True)

        try:
            intent = self.parser.parse(message, payload.get("participants"))
        except LongCatAPIError as exc:
            return self._longcat_error(exc)

        intent = self.constraint_builder.normalize(intent)
        context = self.context_builder.build(intent, payload.get("user_context"))
        if isinstance(context, dict):
            return self._error(context["code"], context["message"], context["recoverable"])

        plan = self.planner.generate_plan(context)
        try:
            plan.final_message = self.response_generator.summarize_plan(plan)
        except LongCatAPIError as exc:
            return self._longcat_error(exc)

        self.store.save(plan)
        return {"success": True, "data": plan.to_dict(), "error": None}

    def confirm(self, payload: dict) -> dict:
        plan_id = payload.get("plan_id")
        plan = self.store.get(plan_id)
        if not plan:
            return self._error("PLAN_NOT_FOUND", "找不到这个方案，请重新生成计划。", False)
        action_ids = payload.get("confirmed_action_ids")
        result: ExecutionResult = self.executor.execute(plan, action_ids)
        return {"success": True, "data": result.to_dict(), "error": None}

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
