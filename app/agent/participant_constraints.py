from __future__ import annotations

from app.domain.models import Constraint, ParticipantProfile, PlanningIntent


class ParticipantConstraintBuilder:
    """Normalizes companion roles into planning constraints."""

    def normalize(self, intent: PlanningIntent) -> PlanningIntent:
        for participant in intent.participants:
            participant.constraints = self._merge_defaults(participant)
        intent.scenario_tags = self._scenario_tags(intent)
        return intent

    def _scenario_tags(self, intent: PlanningIntent) -> list[str]:
        tags = set(intent.scenario_tags)
        tags.update(intent.preferences)

        relation_tags = {
            "spouse": ["spouse", "family"],
            "partner": ["partner", "date"],
            "child": ["child", "kid_friendly"],
            "friend_group": ["friend_group"],
            "bestie": ["bestie", "photo_friendly", "afternoon_tea"],
            "pet": ["pet", "pet_friendly"],
            "elder": ["elder", "low_walking"],
            "colleague": ["colleague", "team_building"],
            "client": ["client", "business"],
        }

        for participant in intent.participants:
            tags.update(relation_tags.get(participant.relation, []))
            for constraint in participant.constraints:
                if constraint.priority in {"hard", "high", "medium"} and constraint.value:
                    tags.add(constraint.value)

        return sorted(tags)

    def _merge_defaults(self, participant: ParticipantProfile) -> list[Constraint]:
        constraints = list(participant.constraints)
        existing = {(item.type, item.value) for item in constraints}

        defaults = {
            "partner": [Constraint("atmosphere", "date", "high")],
            "bestie": [
                Constraint("activity", "photo_friendly", "medium"),
                Constraint("atmosphere", "chat_friendly", "medium"),
            ],
            "pet": [
                Constraint("activity", "pet_friendly", "hard"),
                Constraint("transport", "pet_allowed", "hard"),
            ],
            "elder": [
                Constraint("mobility", "low_walking", "hard"),
                Constraint("atmosphere", "quiet", "medium"),
            ],
            "colleague": [
                Constraint("activity", "group_friendly", "high"),
                Constraint("budget", "budget_control", "medium"),
            ],
            "client": [
                Constraint("atmosphere", "business", "high"),
                Constraint("transport", "transit_accessible", "medium"),
            ],
        }

        for constraint in defaults.get(participant.relation, []):
            if (constraint.type, constraint.value) not in existing:
                constraints.append(constraint)
        return constraints
