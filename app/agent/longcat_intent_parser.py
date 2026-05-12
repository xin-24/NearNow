from __future__ import annotations

import json
import re
from json import JSONDecodeError
from typing import Any

from app.agent.intent_parser import IntentParser
from app.domain.models import Constraint, ParticipantProfile, PlanningIntent
from app.providers.longcat_client import LongCatAPIError, LongCatClient


class LongCatIntentParser:
    """LLM intent parser that surfaces API failures to the caller."""

    def __init__(self, fallback: IntentParser, client: LongCatClient) -> None:
        self.fallback = fallback
        self.client = client

    def parse(self, message: str, explicit_participants: list[dict] | None = None) -> PlanningIntent:
        fallback_intent = self.fallback.parse(message, explicit_participants)
        if explicit_participants:
            return fallback_intent
        if not self.client.is_configured:
            raise LongCatAPIError("LONGCAT_API_KEY is not configured")

        try:
            parsed = self.client.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是 NearNow 本地活动规划 Agent 的意图解析器。"
                            "只输出 JSON，不要解释。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": self._prompt(message, fallback_intent),
                    },
                ],
                max_tokens=900,
                temperature=0.1,
            )
            data = self._loads_json(parsed)
            return self._to_intent(message, data, fallback_intent)
        except LongCatAPIError:
            raise
        except (ValueError, TypeError, KeyError) as exc:
            raise LongCatAPIError("LongCat intent parsing failed") from exc

    def _prompt(self, message: str, fallback_intent: PlanningIntent) -> str:
        return json.dumps(
            {
                "task": "从一句自然语言活动目标中抽取 PlanningIntent。",
                "message": message,
                "fallback_reference": {
                    "start_time": fallback_intent.start_time,
                    "end_time": fallback_intent.end_time,
                    "radius_km": fallback_intent.radius_km,
                    "preferences": fallback_intent.preferences,
                    "scenario_tags": fallback_intent.scenario_tags,
                },
                "output_schema": {
                    "start_time": "HH:MM",
                    "end_time": "HH:MM",
                    "radius_km": "number",
                    "preferences": ["nearby", "low_calorie", "quiet"],
                    "scenario_tags": ["family", "bestie", "pet_friendly"],
                    "participants": [
                        {
                            "relation": "self|spouse|partner|child|friend_group|bestie|pet|elder|colleague|client|companion",
                            "count": 1,
                            "age": None,
                            "constraints": [
                                {
                                    "type": "diet|activity|mobility|transport|atmosphere|budget|safety",
                                    "value": "kid_friendly|pet_friendly|low_walking|quiet|date|light_food",
                                    "priority": "hard|high|medium|low",
                                }
                            ],
                        }
                    ],
                },
            },
            ensure_ascii=False,
        )

    def _loads_json(self, content: str) -> dict[str, Any]:
        try:
            value = json.loads(content)
        except JSONDecodeError:
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if not match:
                raise ValueError("LongCat response did not include JSON")
            value = json.loads(match.group(0))
        if not isinstance(value, dict):
            raise ValueError("LongCat JSON response must be an object")
        return value

    def _to_intent(self, message: str, data: dict[str, Any], fallback: PlanningIntent) -> PlanningIntent:
        participants = self._participants(data.get("participants")) or fallback.participants
        return PlanningIntent(
            message=message,
            date=fallback.date,
            start_time=self._time_value(data.get("start_time"), fallback.start_time),
            end_time=self._time_value(data.get("end_time"), fallback.end_time),
            participants=participants,
            preferences=self._string_list(data.get("preferences")) or fallback.preferences,
            scenario_tags=self._string_list(data.get("scenario_tags")) or fallback.scenario_tags,
            radius_km=self._radius(data.get("radius_km"), fallback.radius_km),
            required_actions=fallback.required_actions,
        )

    def _participants(self, values: Any) -> list[ParticipantProfile]:
        if not isinstance(values, list):
            return []
        participants: list[ParticipantProfile] = []
        for index, item in enumerate(values):
            if not isinstance(item, dict):
                continue
            relation = self._clean_string(item.get("relation")) or "companion"
            participants.append(
                ParticipantProfile(
                    id=self._clean_string(item.get("id")) or f"{relation}_{index + 1}",
                    relation=relation,
                    count=self._positive_int(item.get("count"), 1),
                    age=self._optional_int(item.get("age")),
                    constraints=self._constraints(item.get("constraints")),
                )
            )
        if not any(participant.relation == "self" for participant in participants):
            participants.insert(0, ParticipantProfile(id="self", relation="self"))
        return participants

    def _constraints(self, values: Any) -> list[Constraint]:
        if not isinstance(values, list):
            return []
        constraints: list[Constraint] = []
        for item in values:
            if not isinstance(item, dict):
                continue
            value = self._clean_string(item.get("value"))
            if not value:
                continue
            priority = self._clean_string(item.get("priority")) or "medium"
            if priority not in {"hard", "high", "medium", "low"}:
                priority = "medium"
            constraints.append(
                Constraint(
                    type=self._clean_string(item.get("type")) or "preference",
                    value=value,
                    priority=priority,
                )
            )
        return constraints

    def _string_list(self, values: Any) -> list[str]:
        if not isinstance(values, list):
            return []
        return [item for item in (self._clean_string(value) for value in values) if item]

    def _time_value(self, value: Any, fallback: str) -> str:
        text = self._clean_string(value)
        return text if re.fullmatch(r"\d{2}:\d{2}", text) else fallback

    def _radius(self, value: Any, fallback: float) -> float:
        try:
            radius = float(value)
        except (TypeError, ValueError):
            return fallback
        return min(max(radius, 1.0), 30.0)

    def _positive_int(self, value: Any, fallback: int) -> int:
        number = self._optional_int(value)
        return number if number and number > 0 else fallback

    def _optional_int(self, value: Any) -> int | None:
        if value in {None, ""}:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _clean_string(self, value: Any) -> str:
        return " ".join(str(value or "").split())
