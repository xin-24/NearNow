import unittest

from app.agent.intent_parser import IntentParser
from app.agent.orchestrator import LocalPlannerAgent
from app.domain.models import Coordinates
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
        agent = LocalPlannerAgent()
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
        agent = LocalPlannerAgent()
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
        agent = LocalPlannerAgent()
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
        agent = LocalPlannerAgent()
        response = agent.plan({"message": "下午帮我安排一个附近活动和晚饭。"})
        self.assertFalse(response["success"])
        self.assertEqual("MISSING_ORIGIN", response["error"]["code"])
        self.assertTrue(response["error"]["recoverable"])

    def test_browser_location_is_used_as_origin(self) -> None:
        agent = LocalPlannerAgent()
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
        agent = LocalPlannerAgent()
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
        agent = LocalPlannerAgent()
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
