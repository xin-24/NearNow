from __future__ import annotations

from app.domain.enums import ActionStatus
from app.domain.models import ExecutionResult, Plan
from app.providers.base import LocalLifeProvider


class ExecutionManager:
    def __init__(self, provider: LocalLifeProvider) -> None:
        self.provider = provider

    def execute(self, plan: Plan, action_ids: list[str] | None = None) -> ExecutionResult:
        selected = set(action_ids or [action.action_id for action in plan.pending_actions])
        results: list[dict] = []

        for action in plan.pending_actions:
            if action.action_id not in selected:
                continue
            try:
                if action.type == "book_activity":
                    payload = self.provider.book_activity(action.payload["activity_id"], action.payload)
                elif action.type == "reserve_restaurant":
                    payload = self.provider.reserve_restaurant(action.payload["restaurant_id"], action.payload)
                elif action.type == "send_notification":
                    content = self._final_itinerary_message(plan)
                    payload = self.provider.send_notification({**action.payload, "content": content})
                else:
                    raise ValueError(f"Unsupported action: {action.type}")
                action.status = ActionStatus.SUCCESS
                result_status = "handoff_required" if payload.get("handoff_required") else "success"
                results.append({"action_id": action.action_id, "type": action.type, **payload, "status": result_status})
            except Exception as exc:  # pragma: no cover - defensive guard for real providers
                action.status = ActionStatus.FAILED
                results.append({"action_id": action.action_id, "type": action.type, "status": "failed", "error": str(exc)})

        success_statuses = {"success", "handoff_required"}
        status = "completed" if all(item["status"] in success_statuses for item in results) else "partial_failed"
        return ExecutionResult(
            plan_id=plan.plan_id,
            execution_status=status,
            results=results,
            final_message=self._final_itinerary_message(plan),
        )

    def _final_itinerary_message(self, plan: Plan) -> str:
        if not plan.schedule:
            return plan.final_message or "当前没有可执行方案。"
        first = plan.schedule[0]
        last = plan.schedule[-1]
        return f"搞定了，{first.start_time} 出发，先去 {plan.schedule[1].name}，{last.start_time} 到 {last.name}。"
