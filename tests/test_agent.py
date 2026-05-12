import json
import os
import tempfile
import unittest
from pathlib import Path

from app.agent.intent_parser import IntentParser
from app.agent.longcat_intent_parser import LongCatIntentParser
from app.agent.longcat_response_generator import LongCatResponseGenerator
from app.agent.orchestrator import LocalPlannerAgent
from app.agent.response_generator import ResponseGenerator
from app.domain.models import Coordinates, PlanningIntent, to_plain
from app.providers.longcat_client import LongCatAPIError, LongCatClient, LongCatConfig, load_env_file
from app.providers.location_provider import MockLocationProvider, OpenStreetMapLocationProvider


USER_CONTEXT = {
    "home_location": "望京 SOHO",
    "city": "北京",
    "coordinates": {"lat": 39.9957, "lng": 116.4813},
}

REAL_LOCATION_CONTEXT = {
    "home_location": "我的当前位置",
    "city": "北京",
    "coordinates": {"lat": 39.99, "lng": 116.48},
    "location_permission_granted": True,
    "location_source": "browser",
    "accuracy_m": 1000,
    "precision": "approximate",
}

REAL_LOCATION_WITH_ADDRESS_CONTEXT = {
    "home_location": "北京 朝阳区 望京 SOHO",
    "city": "北京",
    "coordinates": {"lat": 39.99, "lng": 116.48},
    "location_permission_granted": True,
    "location_source": "browser",
    "accuracy_m": 1000,
    "precision": "approximate",
    "district": "朝阳区",
    "landmark": "望京 SOHO",
    "formatted_address": "北京 朝阳区 望京 SOHO",
    "address_source": "mock_reverse_geocode",
    "address_confidence": "high",
}


class LocationProviderTest(unittest.TestCase):
    def test_reverse_geocode_returns_manual_input_format(self) -> None:
        address = MockLocationProvider().reverse_geocode(Coordinates(39.99, 116.48))
        self.assertEqual("北京", address.city)
        self.assertEqual("朝阳区", address.district)
        self.assertIn("北京 朝阳区", address.formatted_address)

    def test_osm_payload_is_formatted_for_single_location_input(self) -> None:
        address = OpenStreetMapLocationProvider().from_nominatim_payload(
            {
                "display_name": "Financial District, Manhattan, New York, United States",
                "address": {
                    "city": "New York;Nueva York",
                    "borough": "Manhattan",
                    "neighbourhood": "Financial District",
                },
            }
        )
        self.assertEqual("New York", address.city)
        self.assertEqual("Manhattan", address.district)
        self.assertEqual("Financial District", address.landmark)
        self.assertEqual("New York Manhattan Financial District", address.formatted_address)


class LongCatIntegrationTest(unittest.TestCase):
    def test_load_env_file_sets_longcat_key_without_overriding_existing_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "LONGCAT_API_KEY=from_file",
                        "LONGCAT_MODEL=LongCat-Flash-Chat",
                    ]
                ),
                encoding="utf-8",
            )
            original_key = os.environ.pop("LONGCAT_API_KEY", None)
            original_model = os.environ.get("LONGCAT_MODEL")
            os.environ["LONGCAT_MODEL"] = "already_exported"
            try:
                load_env_file(env_file)
                self.assertEqual("from_file", os.environ["LONGCAT_API_KEY"])
                self.assertEqual("already_exported", os.environ["LONGCAT_MODEL"])
            finally:
                if original_key is None:
                    os.environ.pop("LONGCAT_API_KEY", None)
                else:
                    os.environ["LONGCAT_API_KEY"] = original_key
                if original_model is None:
                    os.environ.pop("LONGCAT_MODEL", None)
                else:
                    os.environ["LONGCAT_MODEL"] = original_model

    def test_agent_returns_error_without_api_key(self) -> None:
        agent = LocalPlannerAgent(
            llm_client=LongCatClient(
                LongCatConfig(api_key=None, base_url="https://api.longcat.chat", model="LongCat-Flash-Chat")
            )
        )
        response = agent.plan(
            {
                "message": "下午带狗出去玩，顺便找个能带宠物的地方吃饭。",
                "user_context": USER_CONTEXT,
            }
        )
        self.assertFalse(response["success"])
        self.assertEqual("LONGCAT_API_NOT_CONFIGURED", response["error"]["code"])

    def test_agent_returns_error_when_longcat_fails(self) -> None:
        response = LocalPlannerAgent(llm_client=RaisingLongCatClient()).plan(
            {
                "message": "下午带狗出去玩，顺便找个能带宠物的地方吃饭。",
                "user_context": USER_CONTEXT,
            }
        )
        self.assertFalse(response["success"])
        self.assertEqual("LONGCAT_API_ERROR", response["error"]["code"])

    def test_longcat_intent_parser_accepts_json_response(self) -> None:
        client = StubLongCatClient(
            content="""
            {
              "start_time": "15:00",
              "end_time": "19:00",
              "radius_km": 4,
              "preferences": ["quiet", "photo_friendly"],
              "scenario_tags": ["bestie"],
              "participants": [
                {"relation": "bestie", "count": 1, "constraints": [
                  {"type": "activity", "value": "photo_friendly", "priority": "medium"}
                ]}
              ]
            }
            """
        )
        intent = LongCatIntentParser(IntentParser(), client).parse("下午和闺蜜拍照喝咖啡，别太吵。")
        self.assertEqual("15:00", intent.start_time)
        self.assertEqual(4.0, intent.radius_km)
        self.assertIn("bestie", {participant.relation for participant in intent.participants})
        self.assertIn("photo_friendly", intent.preferences)

    def test_longcat_response_generator_uses_model_content(self) -> None:
        client = SequencedLongCatClient(
            [
                json.dumps(to_intent_payload(IntentParser().parse("下午和恋人约会，想有点仪式感。")), ensure_ascii=False),
                "15:00 出发，先活动再吃饭，确认后我来预约。",
            ]
        )
        agent = LocalPlannerAgent(llm_client=client)
        planned = agent.plan({"message": "下午和恋人约会，想有点仪式感。", "user_context": USER_CONTEXT})
        self.assertTrue(planned["success"], planned)
        self.assertEqual("15:00 出发，先活动再吃饭，确认后我来预约。", planned["data"]["final_message"])

    def test_longcat_response_generator_raises_on_error(self) -> None:
        generator = LongCatResponseGenerator(ResponseGenerator(), RaisingLongCatClient())
        agent = test_agent()
        context = agent.context_builder.build(IntentParser().parse("下午和恋人约会。"), USER_CONTEXT)
        self.assertNotIsInstance(context, dict)
        plan = agent.planner.generate_plan(context)
        with self.assertRaises(LongCatAPIError):
            generator.summarize_plan(plan)


class StubLongCatClient:
    is_configured = True

    def __init__(self, content: str) -> None:
        self.content = content

    def chat(self, messages: list[dict[str, str]], *, max_tokens: int = 1200, temperature: float = 0.2) -> str:
        return self.content


class SequencedLongCatClient:
    is_configured = True

    def __init__(self, contents: list[str]) -> None:
        self.contents = contents

    def chat(self, messages: list[dict[str, str]], *, max_tokens: int = 1200, temperature: float = 0.2) -> str:
        if not self.contents:
            raise LongCatAPIError("no stub response")
        return self.contents.pop(0)


class RuleBackedLongCatClient:
    is_configured = True

    def chat(self, messages: list[dict[str, str]], *, max_tokens: int = 1200, temperature: float = 0.2) -> str:
        if "意图解析器" in messages[0]["content"]:
            request = json.loads(messages[-1]["content"])
            intent = IntentParser().parse(request["message"])
            return json.dumps(to_intent_payload(intent), ensure_ascii=False)
        request = json.loads(messages[-1]["content"])
        return request.get("fallback_summary", "方案已生成。")


class RaisingLongCatClient:
    is_configured = True

    def chat(self, messages: list[dict[str, str]], *, max_tokens: int = 1200, temperature: float = 0.2) -> str:
        raise LongCatAPIError("boom")


def to_intent_payload(intent: PlanningIntent) -> dict:
    return {
        "start_time": intent.start_time,
        "end_time": intent.end_time,
        "radius_km": intent.radius_km,
        "preferences": intent.preferences,
        "scenario_tags": intent.scenario_tags,
        "participants": to_plain(intent.participants),
    }


def test_agent() -> LocalPlannerAgent:
    return LocalPlannerAgent(llm_client=RuleBackedLongCatClient())


class IntentParserTest(unittest.TestCase):
    def test_parses_pet_constraints(self) -> None:
        intent = IntentParser().parse("下午带狗出去玩，顺便找个能带宠物的地方吃饭。")
        relations = {participant.relation for participant in intent.participants}
        self.assertIn("pet", relations)
        self.assertIn("pet_friendly", intent.scenario_tags)

    def test_parses_bestie_constraints(self) -> None:
        intent = IntentParser().parse("和闺蜜下午逛逛，想拍照喝下午茶，不想太吵。")
        relations = {participant.relation for participant in intent.participants}
        self.assertIn("bestie", relations)
        self.assertIn("photo_friendly", intent.scenario_tags)


class LocalPlannerAgentTest(unittest.TestCase):
    def test_pet_plan_uses_pet_friendly_places(self) -> None:
        agent = test_agent()
        response = agent.plan(
            {
                "message": "下午带狗出去玩，顺便找个能带宠物的地方吃饭。",
                "user_context": USER_CONTEXT,
            }
        )
        self.assertTrue(response["success"], response)
        names = " ".join(item["name"] for item in response["data"]["schedule"])
        self.assertIn("宠物", names)

    def test_elder_plan_has_low_walking_summary(self) -> None:
        agent = test_agent()
        response = agent.plan(
            {
                "message": "陪爸妈附近走走，别太累，晚饭清淡一点。",
                "user_context": USER_CONTEXT,
            }
        )
        self.assertTrue(response["success"], response)
        summary = " ".join(response["data"]["participant_summary"])
        self.assertIn("少走路", summary)

    def test_confirm_executes_pending_actions(self) -> None:
        agent = test_agent()
        planned = agent.plan(
            {
                "message": "周末和恋人约会，想有点仪式感，别太贵。",
                "user_context": USER_CONTEXT,
            }
        )
        plan_id = planned["data"]["plan_id"]
        action_ids = [item["action_id"] for item in planned["data"]["pending_actions"]]
        confirmed = agent.confirm({"plan_id": plan_id, "confirmed_action_ids": action_ids})
        self.assertTrue(confirmed["success"], confirmed)
        self.assertEqual("completed", confirmed["data"]["execution_status"])

    def test_missing_origin_is_recoverable(self) -> None:
        agent = test_agent()
        response = agent.plan({"message": "下午帮我安排一个附近活动和晚饭。"})
        self.assertFalse(response["success"])
        self.assertEqual("MISSING_ORIGIN", response["error"]["code"])
        self.assertTrue(response["error"]["recoverable"])

    def test_browser_location_is_used_as_origin(self) -> None:
        agent = test_agent()
        response = agent.plan(
            {
                "message": "下午带狗出去玩，顺便找个能带宠物的地方吃饭。",
                "user_context": REAL_LOCATION_CONTEXT,
            }
        )
        self.assertTrue(response["success"], response)
        first_stop = response["data"]["schedule"][0]
        self.assertIn("我的大概位置", first_stop["name"])
        self.assertNotIn("精度约", first_stop["name"])

    def test_browser_location_address_is_used_as_origin(self) -> None:
        agent = test_agent()
        response = agent.plan(
            {
                "message": "下午带狗出去玩，顺便找个能带宠物的地方吃饭。",
                "user_context": REAL_LOCATION_WITH_ADDRESS_CONTEXT,
            }
        )
        self.assertTrue(response["success"], response)
        first_stop = response["data"]["schedule"][0]
        self.assertIn("北京 朝阳区 望京 SOHO", first_stop["name"])

    def test_manual_location_format_is_normalized(self) -> None:
        agent = test_agent()
        response = agent.plan(
            {
                "message": "下午和朋友附近吃饭，再找个地方逛逛。",
                "user_context": {
                    "home_location": "北京/朝阳区/望京 SOHO",
                    "city": "北京",
                    "coordinates": {"lat": 39.9957, "lng": 116.4813},
                    "location_source": "manual",
                    "manual_location_format": "city_district_landmark",
                    "precision": "manual_area",
                },
            }
        )
        self.assertTrue(response["success"], response)
        first_stop = response["data"]["schedule"][0]
        self.assertIn("北京 朝阳区 望京 SOHO", first_stop["name"])


if __name__ == "__main__":
    unittest.main()
