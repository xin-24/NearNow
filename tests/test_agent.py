import json
import os
import tempfile
import unittest
from pathlib import Path

from app.auth import AuthError, AuthService
from app.agent.context_builder import ContextBuilder
from app.agent.intent_parser import IntentParser
from app.agent.longcat_intent_parser import LongCatIntentParser
from app.agent.longcat_response_generator import LongCatResponseGenerator
from app.agent.orchestrator import LocalPlannerAgent
from app.agent.participant_constraints import ParticipantConstraintBuilder
from app.agent.planner import PlanningEngine
from app.agent.response_generator import ResponseGenerator
from app.domain.models import Activity, Constraint, Coordinates, ParticipantProfile, PlanningIntent, Restaurant, RouteOption, to_plain
from app.providers.longcat_client import LongCatAPIError, LongCatClient, LongCatConfig, load_env_file
from app.providers.location_provider import ApproximateAddress, MockLocationProvider, OpenStreetMapLocationProvider
from app.providers.mock_provider import MockLocalLifeProvider
from app.providers.real_provider import OpenStreetMapLocalLifeProvider
from app.storage.repository import MemoryAppRepository


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

    def test_geocode_candidates_include_structured_manual_address(self) -> None:
        candidates = OpenStreetMapLocationProvider()._geocode_candidate_params(
            "北京 朝阳区 望京 SOHO",
            city="北京",
            district="朝阳区",
            landmark="望京 SOHO",
        )
        self.assertIn({"q": "北京 朝阳区 望京 SOHO"}, candidates)
        self.assertIn(
            {"country": "中国", "city": "北京", "county": "朝阳区", "street": "望京 SOHO"},
            candidates,
        )

    def test_geocode_confidence_requires_landmark_match(self) -> None:
        provider = OpenStreetMapLocationProvider()
        self.assertTrue(
            provider._geocode_result_is_confident(
                {"display_name": "小望京, 望京街道, 朝阳区, 北京"},
                city="北京",
                district="朝阳区",
                landmark="小望京",
            )
        )
        self.assertFalse(
            provider._geocode_result_is_confident(
                {"display_name": "北京商务中心区, 呼家楼街道, 朝阳区, 北京"},
                city="北京",
                district="朝阳区",
                landmark="望京 SOHO",
            )
        )


class ParticipantConstraintTest(unittest.TestCase):
    def test_participant_roles_are_added_to_search_tags(self) -> None:
        intent = PlanningIntent(
            message="下午和老婆孩子朋友出去玩",
            preferences=["nearby"],
            scenario_tags=["family", "friend_group"],
            participants=[
                ParticipantProfile(relation="self"),
                ParticipantProfile(relation="spouse"),
                ParticipantProfile(
                    relation="child",
                    constraints=[Constraint("activity", "kid_friendly", "high")],
                ),
                ParticipantProfile(relation="friend_group"),
            ],
        )

        normalized = ParticipantConstraintBuilder().normalize(intent)

        self.assertIn("child", normalized.scenario_tags)
        self.assertIn("kid_friendly", normalized.scenario_tags)
        self.assertIn("spouse", normalized.scenario_tags)


class RealLocalLifeProviderTest(unittest.TestCase):
    def test_overpass_payload_builds_activity_and_restaurant_models(self) -> None:
        provider = OpenStreetMapLocalLifeProvider(max_results=5)
        origin = Coordinates(39.9957, 116.4813)

        activities = provider.from_overpass_activities_payload(
            {
                "elements": [
                    {
                        "type": "node",
                        "id": 1,
                        "lat": 39.991,
                        "lon": 116.476,
                        "tags": {"name": "望湖公园", "leisure": "park", "dog": "yes"},
                    }
                ]
            },
            ["pet", "pet_friendly"],
            2,
            origin,
        )
        self.assertEqual("望湖公园", activities[0].name)
        self.assertEqual("osm_overpass", activities[0].provider)
        self.assertFalse(activities[0].reservation_required)
        self.assertIn("pet_friendly", activities[0].tags)

        restaurants = provider.from_overpass_restaurants_payload(
            {
                "elements": [
                    {
                        "type": "way",
                        "id": 2,
                        "center": {"lat": 39.992, "lon": 116.477},
                        "tags": {
                            "name": "松木咖啡",
                            "amenity": "cafe",
                            "cuisine": "coffee;vegetarian",
                            "dogs": "yes",
                        },
                    }
                ]
            },
            ["bestie"],
            2,
            origin,
        )
        self.assertEqual("松木咖啡", restaurants[0].name)
        self.assertIn("low_calorie", restaurants[0].tags)
        self.assertIn("pet_friendly", restaurants[0].tags)

    def test_osrm_payload_builds_route_option(self) -> None:
        route = OpenStreetMapLocalLifeProvider().from_osrm_payload(
            {"code": "Ok", "routes": [{"distance": 3200, "duration": 720}]},
            "出发地",
            "目的地",
            "driving",
        )
        self.assertEqual(12, route.duration_minutes)
        self.assertEqual(3.2, route.distance_km)
        self.assertEqual("driving", route.mode)


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
        agent = LocalPlannerAgent(llm_client=client, default_mode="mock")
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


class AuthStorageTest(unittest.TestCase):
    def test_login_creates_session_and_reuses_password(self) -> None:
        repository = MemoryAppRepository()
        auth = AuthService(repository)

        created = auth.login_or_register("Xin", "secret123", "小明")
        self.assertEqual("xin", created["user"]["username"])
        self.assertEqual("小明", created["user"]["display_name"])
        self.assertTrue(auth.authenticate(created["token"]))

        with self.assertRaises(AuthError):
            auth.login_or_register("xin", "wrong123")

        auth.logout(created["token"])
        self.assertIsNone(auth.authenticate(created["token"]))

    def test_repository_stores_companions_plan_and_notifications(self) -> None:
        repository = MemoryAppRepository()
        user = repository.create_user(
            user_id="user_1",
            username="xin",
            display_name="Xin",
            password_hash="hash",
            password_salt="salt",
        )
        companions = repository.save_companions(
            user_id=user.user_id,
            companions=[
                {"name": "小张", "relation": "朋友", "contact_value": "13800000000"},
                {"name": "Lily", "relation": "闺蜜", "contact_value": "lily@example.com"},
            ],
        )
        self.assertEqual(2, len(companions))
        self.assertEqual("phone", companions[0]["contact_method"])
        self.assertEqual("email", companions[1]["contact_method"])

        repository.save_user_location(user_id=user.user_id, location=USER_CONTEXT)
        repository.save_plan(
            user_id=user.user_id,
            plan_id="plan_1",
            mode="real",
            message="下午出去玩",
            user_context=USER_CONTEXT,
            plan={"plan_id": "plan_1", "title": "测试计划"},
        )
        repository.save_plan_notification_targets(
            user_id=user.user_id,
            plan_id="plan_1",
            companions=companions,
            message="计划已生成",
        )
        repository.mark_plan_notifications_sent(user_id=user.user_id, plan_id="plan_1", message="准备发送")
        self.assertEqual("ready_to_send", repository.plan_notifications[0]["status"])


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


class StubGeocoder:
    def geocode(
        self,
        query: str,
        city: str | None = None,
        district: str | None = None,
        landmark: str | None = None,
    ) -> ApproximateAddress:
        return ApproximateAddress(
            city="上海",
            district="徐汇区",
            landmark="徐家汇",
            formatted_address="上海 徐汇区 徐家汇",
            source="osm_nominatim",
            precision="approximate_area",
            confidence="high",
            distance_km=0,
            coordinates=Coordinates(31.191, 121.4375),
        )


class SparseRealTagProvider:
    provider_name = "osm_overpass"

    def search_activities(
        self,
        tags: list[str],
        party_size: int,
        radius_km: float,
        origin: Coordinates | None = None,
    ) -> list[Activity]:
        return [
            Activity(
                activity_id="activity_sparse_001",
                name="城市影城",
                category="amenity:cinema",
                location="附近商场",
                coordinates=Coordinates(39.99, 116.48),
                distance_km=1.2,
                duration_minutes=90,
                capacity_left=20,
                tags=["group_friendly", "indoor", "quiet"],
                reservation_required=False,
                provider=self.provider_name,
            )
        ]

    def search_restaurants(
        self,
        tags: list[str],
        party_size: int,
        radius_km: float,
        origin: Coordinates | None = None,
    ) -> list[Restaurant]:
        return [
            Restaurant(
                restaurant_id="restaurant_sparse_001",
                name="社区餐厅",
                location="附近商场",
                coordinates=Coordinates(39.991, 116.481),
                distance_km=1.3,
                available=True,
                table_size=8,
                wait_minutes=0,
                tags=["group_table"],
                reservation_required=False,
                average_price=80,
                provider=self.provider_name,
            )
        ]

    def calculate_routes(
        self,
        origin_name: str,
        origin: Coordinates,
        destination_name: str,
        destination: Coordinates,
        modes: list[str],
    ) -> list[RouteOption]:
        return [
            RouteOption(
                from_name=origin_name,
                to_name=destination_name,
                mode="ride_hailing",
                duration_minutes=12,
                distance_km=2.1,
                estimated_cost=18,
                comfort_score=0.9,
                kid_friendly_score=0.88,
                walking_minutes=4,
            )
        ]

    def book_activity(self, activity_id: str, payload: dict) -> dict:
        return {"status": "ready"}

    def reserve_restaurant(self, restaurant_id: str, payload: dict) -> dict:
        return {"status": "ready"}

    def send_notification(self, payload: dict) -> dict:
        return {"status": "ready"}


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
    return LocalPlannerAgent(llm_client=RuleBackedLongCatClient(), default_mode="mock")


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
    def test_child_constraints_are_preferences_when_real_tags_are_sparse(self) -> None:
        intent = IntentParser().parse("下午和老婆孩子、朋友出去玩几个小时，别离家太远。")
        intent = ParticipantConstraintBuilder().normalize(intent)
        context = ContextBuilder().build(intent, USER_CONTEXT)
        self.assertNotIsInstance(context, dict)

        plan = PlanningEngine(SparseRealTagProvider()).generate_plan(context)

        self.assertNotEqual("需要补充或放宽条件", plan.title)
        self.assertEqual(4, len(plan.schedule))
        self.assertTrue(any("儿童需求已作为强偏好" in note for note in plan.risk_notes))

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

    def test_confirm_applies_selected_route_mode(self) -> None:
        agent = test_agent()
        planned = agent.plan(
            {
                "message": "下午和朋友附近吃饭，再找个地方逛逛。",
                "user_context": USER_CONTEXT,
            }
        )
        self.assertTrue(planned["success"], planned)
        plan_id = planned["data"]["plan_id"]

        confirmed = agent.confirm(
            {
                "plan_id": plan_id,
                "selected_route_mode": "walking",
                "confirmed_action_ids": [item["action_id"] for item in planned["data"]["pending_actions"]],
            }
        )

        self.assertTrue(confirmed["success"], confirmed)
        stored = agent.store.get(plan_id)
        self.assertIsNotNone(stored)
        self.assertEqual("walking", stored.schedule[0].transport_mode)
        self.assertTrue(next(route for route in stored.route_options if route.mode == "walking").selected)

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

    def test_real_mode_geocodes_manual_location_before_planning(self) -> None:
        agent = LocalPlannerAgent(llm_client=RuleBackedLongCatClient(), default_mode="real")
        agent.real_provider = MockLocalLifeProvider()
        agent.location_provider = StubGeocoder()
        response = agent.plan(
            {
                "message": "下午和朋友附近吃饭，再找个地方逛逛。",
                "mode": "real",
                "user_context": {
                    "home_location": "上海 徐汇区 徐家汇",
                    "city": "上海",
                    "location_source": "manual",
                    "manual_location_format": "city_district_landmark",
                    "precision": "manual_area",
                },
            }
        )
        self.assertTrue(response["success"], response)
        first_stop = response["data"]["schedule"][0]
        self.assertIn("上海 徐汇区 徐家汇", first_stop["name"])


if __name__ == "__main__":
    unittest.main()
