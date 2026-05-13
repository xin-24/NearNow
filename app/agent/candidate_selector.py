from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from json import JSONDecodeError
from typing import Any

from app.agent.context_builder import PlanningContext
from app.domain.models import Activity, Restaurant, RouteOption, to_plain
from app.providers.longcat_client import LongCatAPIError, LongCatClient


CandidateTuple = tuple[float, Activity, Restaurant, RouteOption, list[RouteOption]]


@dataclass(frozen=True)
class CandidateDecision:
    option_id: str
    route_mode: str
    reasoning: list[str] = field(default_factory=list)


class LongCatCandidateSelector:
    """Uses the LLM to choose among real POI candidates, without inventing places."""

    def __init__(self, client: LongCatClient) -> None:
        self.client = client

    def decide(self, context: PlanningContext, candidates: list[CandidateTuple]) -> CandidateDecision:
        if not candidates:
            raise LongCatAPIError("No candidate options available for AI selection")
        if not self.client.is_configured:
            raise LongCatAPIError("LONGCAT_API_KEY is not configured")

        options = self._candidate_options(candidates)
        try:
            content = self.client.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是 NearNow 的真实 POI 候选决策器。"
                            "只能从候选 JSON 中选择，不允许编造新地点、店铺或交通方式。"
                            "只输出 JSON，不要解释。"
                        ),
                    },
                    {"role": "user", "content": self._prompt(context, options)},
                ],
                max_tokens=1000,
                temperature=0.15,
            )
            return self._parse_decision(content, options)
        except LongCatAPIError:
            raise
        except (TypeError, ValueError, KeyError) as exc:
            raise LongCatAPIError("LongCat candidate selection failed") from exc

    def _prompt(self, context: PlanningContext, options: list[dict[str, Any]]) -> str:
        intent = context.intent
        return json.dumps(
            {
                "task": "从真实 POI 候选中选择最适合当前人物画像和约束的一组活动、餐厅和首段交通方式。",
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
                "origin": {
                    "name": context.origin_name,
                    "city": context.user_context.city,
                    "district": context.user_context.district,
                    "landmark": context.user_context.landmark,
                    "precision": context.user_context.precision,
                },
                "strategy": to_plain(context.strategy) if context.strategy else None,
                "candidate_options": options,
                "rules": [
                    "必须选择 candidate_options 里的 option_id。",
                    "route_mode 必须来自该 option 的 routes 列表。",
                    "不要因为距离最近就忽略人物画像。",
                    "老人优先低强度、可休息、清淡正餐；宠物优先宠物友好和需确认；亲子优先安全适龄。",
                    "如果所有候选都一般，也要在候选中选相对最适合的一项，并说明风险，不要编造新的店。",
                ],
                "output_schema": {
                    "option_id": "option_1",
                    "route_mode": "ride_hailing",
                    "reasoning": ["选择原因 1", "选择原因 2"],
                },
            },
            ensure_ascii=False,
        )

    def _candidate_options(self, candidates: list[CandidateTuple]) -> list[dict[str, Any]]:
        options: list[dict[str, Any]] = []
        for index, (score, activity, restaurant, selected_route, routes) in enumerate(candidates, start=1):
            options.append(
                {
                    "option_id": f"option_{index}",
                    "rule_score": round(score, 2),
                    "activity": {
                        "activity_id": activity.activity_id,
                        "name": activity.name,
                        "category": activity.category,
                        "location": activity.location,
                        "distance_km": activity.distance_km,
                        "duration_minutes": activity.duration_minutes,
                        "tags": activity.tags,
                        "provider": activity.provider,
                    },
                    "restaurant": {
                        "restaurant_id": restaurant.restaurant_id,
                        "name": restaurant.name,
                        "location": restaurant.location,
                        "distance_km": restaurant.distance_km,
                        "wait_minutes": restaurant.wait_minutes,
                        "average_price": restaurant.average_price,
                        "tags": restaurant.tags,
                        "provider": restaurant.provider,
                    },
                    "default_route_mode": selected_route.mode,
                    "routes": [
                        {
                            "mode": route.mode,
                            "duration_minutes": route.duration_minutes,
                            "distance_km": route.distance_km,
                            "estimated_cost": route.estimated_cost,
                            "comfort_score": route.comfort_score,
                            "walking_minutes": route.walking_minutes,
                            "transfer_count": route.transfer_count,
                        }
                        for route in routes
                    ],
                }
            )
        return options

    def _parse_decision(self, content: str, options: list[dict[str, Any]]) -> CandidateDecision:
        data = self._loads_json(content)
        option_id = self._string(data.get("option_id"))
        route_mode = self._string(data.get("route_mode"))
        option = next((item for item in options if item["option_id"] == option_id), None)
        if option is None:
            raise ValueError("LongCat selected an option_id outside candidate_options")

        allowed_modes = {str(route["mode"]) for route in option["routes"]}
        if route_mode not in allowed_modes:
            raise ValueError("LongCat selected a route_mode outside the option routes")

        return CandidateDecision(
            option_id=option_id,
            route_mode=route_mode,
            reasoning=self._string_list(data.get("reasoning")),
        )

    def _loads_json(self, content: str) -> dict[str, Any]:
        try:
            value = json.loads(content)
        except JSONDecodeError:
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if not match:
                raise ValueError("LongCat candidate response did not include JSON")
            value = json.loads(match.group(0))
        if not isinstance(value, dict):
            raise ValueError("LongCat candidate response must be an object")
        return value

    def _string_list(self, values: Any) -> list[str]:
        if not isinstance(values, list):
            return []
        return [item for item in (self._string(value) for value in values) if item]

    def _string(self, value: Any) -> str:
        return " ".join(str(value or "").split())
