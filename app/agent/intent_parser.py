from __future__ import annotations

import re

from app.domain.models import Constraint, ParticipantProfile, PlanningIntent


class IntentParser:
    """Small deterministic parser for the demo scaffold.

    The production version can replace this with an LLM parser while keeping
    the same PlanningIntent contract.
    """

    def parse(self, message: str, explicit_participants: list[dict] | None = None) -> PlanningIntent:
        participants = self._parse_participants(message)
        if explicit_participants:
            participants = self._from_explicit_participants(explicit_participants)

        preferences = self._parse_preferences(message)
        scenario_tags = self._parse_scenario_tags(message, participants, preferences)
        start_time, end_time = self._parse_time_window(message)

        return PlanningIntent(
            message=message,
            start_time=start_time,
            end_time=end_time,
            participants=participants,
            preferences=preferences,
            scenario_tags=scenario_tags,
            radius_km=self._parse_radius(message),
        )

    def _parse_participants(self, message: str) -> list[ParticipantProfile]:
        participants: list[ParticipantProfile] = [ParticipantProfile(id="self", relation="self")]

        if self._contains(message, "老婆", "妻子", "老公", "丈夫", "爱人", "伴侣"):
            participants.append(
                ParticipantProfile(
                    id="spouse",
                    relation="spouse",
                    constraints=self._diet_constraints(message),
                )
            )

        if self._contains(message, "恋人", "男朋友", "女朋友", "约会"):
            participants.append(
                ParticipantProfile(
                    id="partner",
                    relation="partner",
                    constraints=[Constraint("atmosphere", "date", "high")],
                )
            )

        if self._contains(message, "闺蜜", "姐妹"):
            participants.append(
                ParticipantProfile(
                    id="bestie",
                    relation="bestie",
                    constraints=[
                        Constraint("activity", "photo_friendly", "medium"),
                        Constraint("atmosphere", "chat_friendly", "medium"),
                    ],
                )
            )

        if self._contains(message, "孩子", "小孩", "儿童", "娃", "宝宝"):
            age = self._parse_age(message)
            participants.append(
                ParticipantProfile(
                    id="child",
                    relation="child",
                    age=age,
                    constraints=[
                        Constraint("activity", "kid_friendly", "hard"),
                        Constraint("safety", "child_safe", "hard"),
                    ],
                )
            )

        if self._contains(message, "朋友", "哥们", "同学"):
            participants.append(
                ParticipantProfile(
                    id="friends",
                    relation="friend_group",
                    count=self._parse_group_count(message, default=4),
                    constraints=[Constraint("activity", "group_friendly", "medium")],
                )
            )

        if self._contains(message, "狗", "猫", "宠物", "毛孩子"):
            participants.append(
                ParticipantProfile(
                    id="pet",
                    relation="pet",
                    constraints=[
                        Constraint("activity", "pet_friendly", "hard"),
                        Constraint("transport", "pet_allowed", "hard"),
                    ],
                )
            )

        if self._contains(message, "爸妈", "父母", "老人", "长辈"):
            participants.append(
                ParticipantProfile(
                    id="elder",
                    relation="elder",
                    count=2 if self._contains(message, "爸妈", "父母") else 1,
                    constraints=[
                        Constraint("mobility", "low_walking", "hard"),
                        Constraint("diet", "light_food", "medium"),
                    ],
                )
            )

        if self._contains(message, "同事", "团建", "客户"):
            relation = "client" if "客户" in message else "colleague"
            participants.append(
                ParticipantProfile(
                    id=relation,
                    relation=relation,
                    count=self._parse_group_count(message, default=6),
                    constraints=[
                        Constraint("activity", "group_friendly", "high"),
                        Constraint("transport", "transit_accessible", "medium"),
                    ],
                )
            )

        return self._dedupe(participants)

    def _from_explicit_participants(self, values: list[dict]) -> list[ParticipantProfile]:
        participants: list[ParticipantProfile] = []
        for index, item in enumerate(values):
            constraints = [
                Constraint(
                    type=constraint.get("type", "preference"),
                    value=constraint.get("value", ""),
                    priority=constraint.get("priority", "medium"),
                )
                for constraint in item.get("constraints", [])
            ]
            participants.append(
                ParticipantProfile(
                    id=item.get("id") or f"participant_{index + 1}",
                    relation=item.get("relation", "companion"),
                    count=int(item.get("count", 1)),
                    age=item.get("age"),
                    constraints=constraints,
                )
            )
        return participants or [ParticipantProfile(id="self", relation="self")]

    def _parse_preferences(self, message: str) -> list[str]:
        preferences: list[str] = []
        mapping = {
            "nearby": ("附近", "别太远", "离家近", "周边"),
            "low_calorie": ("减肥", "低脂", "轻食", "清淡"),
            "quiet": ("安静", "不吵", "聊天"),
            "photo_friendly": ("拍照", "出片", "好看"),
            "date": ("约会", "仪式感", "浪漫"),
            "pet_friendly": ("宠物", "狗", "猫", "毛孩子"),
            "low_walking": ("少走路", "别太累", "不累"),
            "budget_control": ("预算", "别太贵", "人均"),
        }
        for key, words in mapping.items():
            if self._contains(message, *words):
                preferences.append(key)
        return preferences

    def _parse_scenario_tags(
        self,
        message: str,
        participants: list[ParticipantProfile],
        preferences: list[str],
    ) -> list[str]:
        tags = set(preferences)
        for participant in participants:
            tags.add(participant.relation)
        if self._contains(message, "下午茶", "咖啡"):
            tags.add("afternoon_tea")
        if self._contains(message, "展", "展览", "市集"):
            tags.add("exhibition")
        if self._contains(message, "团建"):
            tags.add("team_building")
        return sorted(tags)

    def _parse_time_window(self, message: str) -> tuple[str, str]:
        if "晚上" in message:
            return "18:00", "21:00"
        if "上午" in message:
            return "09:30", "12:30"
        match = re.search(r"(\d{1,2})[:点](?:\d{2})?", message)
        if match:
            hour = int(match.group(1))
            start = f"{hour:02d}:00"
            end = f"{min(hour + 4, 23):02d}:00"
            return start, end
        return "14:00", "18:00"

    def _parse_radius(self, message: str) -> float:
        if self._contains(message, "步行", "走路"):
            return 2.5
        if self._contains(message, "别太远", "附近", "离家近"):
            return 6.0
        return 8.0

    def _parse_age(self, message: str) -> int | None:
        match = re.search(r"(\d{1,2})\s*岁", message)
        return int(match.group(1)) if match else None

    def _parse_group_count(self, message: str, default: int) -> int:
        match = re.search(r"(\d{1,2})\s*(?:个|位)?(?:朋友|同事|人)", message)
        return int(match.group(1)) if match else default

    def _diet_constraints(self, message: str) -> list[Constraint]:
        constraints: list[Constraint] = []
        if self._contains(message, "减肥", "低脂", "轻食"):
            constraints.append(Constraint("diet", "low_calorie", "medium"))
        if "清淡" in message:
            constraints.append(Constraint("diet", "light_food", "medium"))
        return constraints

    def _dedupe(self, participants: list[ParticipantProfile]) -> list[ParticipantProfile]:
        seen: set[str] = set()
        unique: list[ParticipantProfile] = []
        for participant in participants:
            key = participant.id or participant.relation
            if key not in seen:
                seen.add(key)
                unique.append(participant)
        return unique

    def _contains(self, message: str, *words: str) -> bool:
        return any(word in message for word in words)

