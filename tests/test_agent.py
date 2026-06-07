import json
import os
import tempfile
import unittest
from pathlib import Path

from app.auth import AuthError, AuthService
from app.agent.candidate_selector import LongCatCandidateSelector
from app.agent.context_builder import ContextBuilder
from app.agent.executor import ExecutionManager
from app.agent.intent_parser import IntentParser
from app.agent.longcat_intent_parser import LongCatIntentParser
from app.agent.longcat_response_generator import LongCatResponseGenerator
from app.agent.orchestrator import LocalPlannerAgent
from app.agent.participant_constraints import ParticipantConstraintBuilder
from app.agent.planner import PlanningEngine
from app.agent.response_generator import ResponseGenerator
from app.agent.strategy import LongCatStrategyBuilder, PersonaStrategyBuilder
from app.domain.models import Activity, Constraint, Coordinates, ParticipantProfile, PlanningIntent, Restaurant, RouteOption, to_plain
from app.providers.longcat_client import LongCatAPIError, LongCatClient, LongCatConfig, load_env_file
from app.providers.amap_provider import AmapLocalLifeProvider, AmapLocationProvider
from app.providers.location_provider import ApproximateAddress, MockLocationProvider, OpenStreetMapLocationProvider
from app.providers.meituan_link import HandoffLinkBuilder
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
            {
                "code": "Ok",
                "routes": [
                    {
                        "distance": 3200,
                        "duration": 720,
                        "geometry": {"coordinates": [[116.48, 39.99], [116.49, 39.995]]},
                    }
                ],
            },
            "出发地",
            "目的地",
            "driving",
        )
        self.assertEqual(12, route.duration_minutes)
        self.assertEqual(3.2, route.distance_km)
        self.assertEqual("driving", route.mode)
        self.assertEqual(2, len(route.route_geometry))
        self.assertEqual(39.99, route.route_geometry[0].lat)

    def test_osm_tags_are_inferred_from_place_type_not_blind_persona(self) -> None:
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
                        "tags": {"name": "小巷咖啡", "amenity": "cafe"},
                    },
                    {
                        "type": "node",
                        "id": 2,
                        "lat": 39.992,
                        "lon": 116.477,
                        "tags": {"name": "城市影院", "amenity": "cinema"},
                    },
                ]
            },
            ["bestie"],
            2,
            origin,
        )
        by_name = {item.name: item for item in activities}
        self.assertIn("bestie", by_name["小巷咖啡"].tags)
        self.assertNotIn("bestie", by_name["城市影院"].tags)

        restaurants = provider.from_overpass_restaurants_payload(
            {
                "elements": [
                    {
                        "type": "node",
                        "id": 3,
                        "lat": 39.993,
                        "lon": 116.478,
                        "tags": {"name": "普通餐厅", "amenity": "restaurant"},
                    }
                ]
            },
            ["bestie"],
            2,
            origin,
        )
        self.assertNotIn("bestie", restaurants[0].tags)

    def test_outdoor_seating_marks_restaurant_as_pet_possible(self) -> None:
        provider = OpenStreetMapLocalLifeProvider(max_results=5)
        restaurants = provider.from_overpass_restaurants_payload(
            {
                "elements": [
                    {
                        "type": "node",
                        "id": 1,
                        "lat": 39.993,
                        "lon": 116.478,
                        "tags": {
                            "name": "露台咖啡",
                            "amenity": "cafe",
                            "outdoor_seating": "yes",
                        },
                    }
                ]
            },
            ["pet", "pet_friendly"],
            2,
            Coordinates(39.9957, 116.4813),
        )

        self.assertIn("pet_possible", restaurants[0].tags)
        self.assertNotIn("pet_friendly", restaurants[0].tags)

    def test_elder_stroll_tags_prefer_park_and_mall_over_library(self) -> None:
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
                        "tags": {"name": "社区图书馆", "amenity": "library"},
                    },
                    {
                        "type": "node",
                        "id": 2,
                        "lat": 39.992,
                        "lon": 116.477,
                        "tags": {"name": "街心花园", "leisure": "garden"},
                    },
                    {
                        "type": "node",
                        "id": 3,
                        "lat": 39.993,
                        "lon": 116.478,
                        "tags": {"name": "生活广场", "shop": "mall"},
                    },
                ]
            },
            ["elder", "stroll", "low_walking"],
            3,
            origin,
        )
        by_name = {item.name: item for item in activities}
        self.assertIn("stroll_friendly", by_name["街心花园"].tags)
        self.assertIn("stroll_friendly", by_name["生活广场"].tags)
        self.assertNotIn("stroll_friendly", by_name["社区图书馆"].tags)
        self.assertNotIn("bestie", by_name["社区图书馆"].tags)

    def test_persona_filters_focus_osm_activity_search(self) -> None:
        provider = OpenStreetMapLocalLifeProvider(max_results=5)
        elder_filters = provider._activity_filters(["elder", "stroll", "low_walking"])
        bestie_filters = provider._activity_filters(["bestie", "afternoon_tea"])

        self.assertIn(("leisure", "park"), elder_filters)
        self.assertIn(("shop", "mall"), elder_filters)
        self.assertNotIn(("amenity", "cinema"), elder_filters)
        self.assertIn(("amenity", "cafe"), bestie_filters)

    def test_persona_filters_focus_osm_restaurant_search(self) -> None:
        provider = OpenStreetMapLocalLifeProvider(max_results=5)
        elder_filters = provider._restaurant_filters(["elder", "proper_meal", "light_food"])
        bestie_filters = provider._restaurant_filters(["bestie", "afternoon_tea"])

        self.assertIn(("amenity", "restaurant"), elder_filters)
        self.assertIn(("amenity", "food_court"), elder_filters)
        self.assertNotIn(("amenity", "cafe"), elder_filters)
        self.assertIn(("amenity", "cafe"), bestie_filters)

    def test_cafe_is_not_treated_as_elder_dinner_by_default(self) -> None:
        provider = OpenStreetMapLocalLifeProvider(max_results=5)
        restaurants = provider.from_overpass_restaurants_payload(
            {
                "elements": [
                    {
                        "type": "node",
                        "id": 1,
                        "lat": 39.993,
                        "lon": 116.478,
                        "tags": {"name": "瑞幸咖啡", "amenity": "cafe"},
                    },
                    {
                        "type": "node",
                        "id": 2,
                        "lat": 39.994,
                        "lon": 116.479,
                        "tags": {"name": "清和小馆", "amenity": "restaurant", "cuisine": "chinese"},
                    },
                ]
            },
            ["elder", "proper_meal", "light_food"],
            3,
            Coordinates(39.9957, 116.4813),
        )
        by_name = {item.name: item for item in restaurants}
        self.assertIn("beverage_only", by_name["瑞幸咖啡"].tags)
        self.assertNotIn("proper_meal", by_name["瑞幸咖啡"].tags)
        self.assertIn("proper_meal", by_name["清和小馆"].tags)

    def test_heavy_food_is_marked_for_elder_light_meal_ranking(self) -> None:
        provider = OpenStreetMapLocalLifeProvider(max_results=5)
        restaurants = provider.from_overpass_restaurants_payload(
            {
                "elements": [
                    {
                        "type": "node",
                        "id": 1,
                        "lat": 39.993,
                        "lon": 116.478,
                        "tags": {"name": "呷哺呷哺", "amenity": "restaurant"},
                    }
                ]
            },
            ["elder", "proper_meal", "light_food"],
            3,
            Coordinates(39.9957, 116.4813),
        )

        self.assertIn("heavy_food", restaurants[0].tags)

    def test_noodle_shop_is_marked_as_quick_meal(self) -> None:
        provider = OpenStreetMapLocalLifeProvider(max_results=5)
        restaurants = provider.from_overpass_restaurants_payload(
            {
                "elements": [
                    {
                        "type": "node",
                        "id": 1,
                        "lat": 39.993,
                        "lon": 116.478,
                        "tags": {"name": "手耕扯面", "amenity": "restaurant"},
                    }
                ]
            },
            ["partner", "date"],
            2,
            Coordinates(39.9957, 116.4813),
        )

        self.assertIn("quick_meal", restaurants[0].tags)
        self.assertIn("casual_meal", restaurants[0].tags)


class AmapProviderTest(unittest.TestCase):
    def test_amap_regeo_payload_is_formatted_for_single_location_input(self) -> None:
        address = AmapLocationProvider().from_regeo_payload(
            {
                "regeocode": {
                    "formatted_address": "北京市朝阳区望京街道望京SOHO",
                    "addressComponent": {
                        "province": "北京市",
                        "city": [],
                        "district": "朝阳区",
                        "township": "望京街道",
                    },
                }
            },
            Coordinates(39.9957, 116.4813),
        )

        self.assertEqual("北京市", address.city)
        self.assertEqual("朝阳区", address.district)
        self.assertEqual("望京街道", address.landmark)
        self.assertEqual("amap_geocode", address.source)

    def test_amap_place_payload_builds_activity_and_restaurant_models(self) -> None:
        provider = AmapLocalLifeProvider(api_key="test", max_results=5)
        origin = Coordinates(39.9957, 116.4813)

        activities = provider.from_amap_activity_pois(
            [
                {
                    "id": "B000A1",
                    "name": "望湖公园",
                    "type": "风景名胜;公园广场;公园",
                    "typecode": "110101",
                    "address": "望京街道",
                    "location": "116.476,39.991",
                    "distance": "620",
                }
            ],
            ["pet", "pet_friendly"],
            2,
            origin,
        )
        self.assertEqual("望湖公园", activities[0].name)
        self.assertEqual("amap", activities[0].provider)
        self.assertIn("pet_friendly", activities[0].tags)

        restaurants = provider.from_amap_restaurant_pois(
            [
                {
                    "id": "B000R1",
                    "name": "松木露台咖啡",
                    "type": "餐饮服务;咖啡厅;咖啡厅",
                    "typecode": "050500",
                    "address": "望京SOHO",
                    "location": "116.477,39.992",
                    "distance": "520",
                    "biz_ext": {"cost": "62"},
                }
            ],
            ["bestie", "pet"],
            2,
            origin,
        )
        self.assertEqual("松木露台咖啡", restaurants[0].name)
        self.assertEqual(62, restaurants[0].average_price)
        self.assertIn("bestie", restaurants[0].tags)
        self.assertIn("pet_possible", restaurants[0].tags)

    def test_amap_route_payload_builds_route_option(self) -> None:
        route = AmapLocalLifeProvider(api_key="test")._route_from_v3_path(
            {
                "route": {
                    "paths": [
                        {
                            "distance": "3200",
                            "duration": "720",
                            "steps": [
                                {"polyline": "116.480000,39.990000;116.490000,39.995000"},
                            ],
                        }
                    ]
                }
            },
            "出发地",
            "目的地",
            "driving",
        )

        self.assertEqual(12, route.duration_minutes)
        self.assertEqual(3.2, route.distance_km)
        self.assertEqual("driving", route.mode)
        self.assertEqual(2, len(route.route_geometry))
        self.assertEqual(39.99, route.route_geometry[0].lat)

    def test_amap_calculate_routes_only_requests_single_driving_route(self) -> None:
        provider = AmapLocalLifeProvider(api_key="test")
        requested_modes: list[str] = []
        expected = RouteOption("出发地", "目的地", "driving", 12, 3.2, 0, 0.8, 0.8)

        def calculate_route(
            origin_name: str,
            origin: Coordinates,
            destination_name: str,
            destination: Coordinates,
            mode: str,
        ) -> RouteOption:
            requested_modes.append(mode)
            return expected

        provider._calculate_route = calculate_route
        routes = provider.calculate_routes(
            "出发地",
            Coordinates(39.99, 116.48),
            "目的地",
            Coordinates(39.995, 116.49),
            ["walking", "public_transit", "ride_hailing", "cycling"],
        )

        self.assertEqual(["driving"], requested_modes)
        self.assertEqual([expected], routes)


class PlanningRankingTest(unittest.TestCase):
    def test_candidate_selection_pool_diversifies_repeated_restaurants(self) -> None:
        activity_1 = Activity(
            activity_id="activity_1",
            name="公园",
            category="leisure:park",
            location="附近",
            coordinates=Coordinates(39.99, 116.48),
            distance_km=0.5,
            duration_minutes=60,
            capacity_left=10,
            tags=["stroll_friendly"],
        )
        activity_2 = Activity(
            activity_id="activity_2",
            name="展览",
            category="tourism:gallery",
            location="附近",
            coordinates=Coordinates(39.991, 116.481),
            distance_km=0.8,
            duration_minutes=60,
            capacity_left=10,
            tags=["date"],
        )
        activity_3 = Activity(
            activity_id="activity_3",
            name="商场",
            category="shop:mall",
            location="附近",
            coordinates=Coordinates(39.992, 116.482),
            distance_km=1.0,
            duration_minutes=60,
            capacity_left=10,
            tags=["bestie"],
        )
        repeated = Restaurant(
            restaurant_id="restaurant_noodle",
            name="手耕扯面",
            location="附近",
            coordinates=Coordinates(39.99, 116.48),
            distance_km=0.3,
            available=True,
            table_size=4,
            wait_minutes=0,
            tags=["proper_meal", "quick_meal"],
        )
        bistro = Restaurant(
            restaurant_id="restaurant_bistro",
            name="安静小馆",
            location="附近",
            coordinates=Coordinates(39.991, 116.481),
            distance_km=0.7,
            available=True,
            table_size=4,
            wait_minutes=0,
            tags=["date", "quiet"],
        )
        tea = Restaurant(
            restaurant_id="restaurant_tea",
            name="花园下午茶",
            location="附近",
            coordinates=Coordinates(39.992, 116.482),
            distance_km=1.0,
            available=True,
            table_size=4,
            wait_minutes=0,
            tags=["bestie", "afternoon_tea"],
        )
        route = RouteOption("家", "目的地", "walking", 8, 0.6, 0, 0.7, 0.6)
        candidates = [
            (100.0, activity_1, repeated, route, [route]),
            (99.0, activity_2, repeated, route, [route]),
            (98.0, activity_3, repeated, route, [route]),
            (90.0, activity_1, bistro, route, [route]),
            (89.0, activity_2, tea, route, [route]),
            (88.0, activity_3, bistro, route, [route]),
        ]

        pool = PlanningEngine(MockLocalLifeProvider())._candidate_selection_pool(candidates, 4)

        restaurant_ids = [candidate[2].restaurant_id for candidate in pool]
        self.assertEqual(len(set(restaurant_ids)), 3)
        self.assertLessEqual(restaurant_ids.count("restaurant_noodle"), 2)

    def test_bestie_profile_prefers_chat_and_photo_place(self) -> None:
        intent = PlanningIntent(
            message="和闺蜜下午拍照喝咖啡",
            participants=[ParticipantProfile(relation="self"), ParticipantProfile(relation="bestie")],
            preferences=["photo_friendly"],
            scenario_tags=["bestie", "photo_friendly"],
        )
        context = ContextBuilder().build(ParticipantConstraintBuilder().normalize(intent), USER_CONTEXT)
        self.assertNotIsInstance(context, dict)
        activities = [
            Activity(
                activity_id="date_1",
                name="城市影院",
                category="amenity:cinema",
                location="商场",
                coordinates=Coordinates(39.99, 116.48),
                distance_km=1.0,
                duration_minutes=90,
                capacity_left=10,
                tags=["date", "quiet", "indoor"],
            ),
            Activity(
                activity_id="bestie_1",
                name="花艺下午茶",
                category="amenity:cafe",
                location="商场",
                coordinates=Coordinates(39.991, 116.481),
                distance_km=2.0,
                duration_minutes=75,
                capacity_left=10,
                tags=["bestie", "afternoon_tea", "chat_friendly", "photo_friendly"],
            ),
        ]

        ranked = PlanningEngine(MockLocalLifeProvider())._rank_activity_candidates(activities, context)

        self.assertEqual("花艺下午茶", ranked[0].name)

    def test_partner_profile_prefers_date_place(self) -> None:
        intent = PlanningIntent(
            message="和恋人约会，想有仪式感",
            participants=[ParticipantProfile(relation="self"), ParticipantProfile(relation="partner")],
            preferences=["date"],
            scenario_tags=["partner", "date"],
        )
        context = ContextBuilder().build(ParticipantConstraintBuilder().normalize(intent), USER_CONTEXT)
        self.assertNotIsInstance(context, dict)
        activities = [
            Activity(
                activity_id="group_1",
                name="桌游空间",
                category="amenity:community_centre",
                location="商场",
                coordinates=Coordinates(39.99, 116.48),
                distance_km=1.0,
                duration_minutes=90,
                capacity_left=10,
                tags=["group_friendly", "team_building", "indoor"],
            ),
            Activity(
                activity_id="date_1",
                name="河畔艺术展",
                category="tourism:gallery",
                location="艺术中心",
                coordinates=Coordinates(39.991, 116.481),
                distance_km=2.0,
                duration_minutes=75,
                capacity_left=10,
                tags=["date", "quiet", "photo_friendly", "indoor"],
            ),
        ]

        ranked = PlanningEngine(MockLocalLifeProvider())._rank_activity_candidates(activities, context)

        self.assertEqual("河畔艺术展", ranked[0].name)

    def test_elder_stroll_profile_prefers_park_or_mall_over_library(self) -> None:
        intent = IntentParser().parse("陪爸妈附近走走，别太累，晚饭清淡一点。")
        context = ContextBuilder().build(ParticipantConstraintBuilder().normalize(intent), USER_CONTEXT)
        self.assertNotIsInstance(context, dict)
        activities = [
            Activity(
                activity_id="library_1",
                name="社区图书馆",
                category="amenity:library",
                location="社区",
                coordinates=Coordinates(39.99, 116.48),
                distance_km=0.3,
                duration_minutes=60,
                capacity_left=20,
                tags=["indoor", "quiet", "elder_friendly"],
            ),
            Activity(
                activity_id="park_1",
                name="街心花园",
                category="leisure:garden",
                location="社区",
                coordinates=Coordinates(39.991, 116.481),
                distance_km=1.2,
                duration_minutes=60,
                capacity_left=20,
                tags=["outdoor", "low_walking", "elder_friendly", "stroll_friendly"],
            ),
            Activity(
                activity_id="mall_1",
                name="生活广场",
                category="shop:mall",
                location="商场",
                coordinates=Coordinates(39.992, 116.482),
                distance_km=1.4,
                duration_minutes=75,
                capacity_left=20,
                tags=["indoor", "low_walking", "elder_friendly", "stroll_friendly"],
            ),
        ]

        ranked = PlanningEngine(MockLocalLifeProvider())._rank_activity_candidates(activities, context)

        self.assertIn(ranked[0].name, {"街心花园", "生活广场"})

    def test_elder_dinner_profile_prefers_light_meal_over_coffee(self) -> None:
        intent = IntentParser().parse("陪爸妈附近走走，别太累，晚饭清淡一点。")
        context = ContextBuilder().build(ParticipantConstraintBuilder().normalize(intent), USER_CONTEXT)
        self.assertNotIsInstance(context, dict)
        restaurants = [
            Restaurant(
                restaurant_id="coffee_1",
                name="瑞幸咖啡",
                location="楼下",
                coordinates=Coordinates(39.99, 116.48),
                distance_km=0.2,
                available=True,
                table_size=4,
                wait_minutes=0,
                tags=["elder_friendly", "quiet", "beverage_only", "beverage_light"],
            ),
            Restaurant(
                restaurant_id="bbq_1",
                name="烧烤小馆",
                location="楼下",
                coordinates=Coordinates(39.9905, 116.4805),
                distance_km=0.3,
                available=True,
                table_size=4,
                wait_minutes=0,
                tags=["elder_friendly", "proper_meal", "heavy_food", "group_table"],
            ),
            Restaurant(
                restaurant_id="meal_1",
                name="清和小馆",
                location="商场",
                coordinates=Coordinates(39.991, 116.481),
                distance_km=1.0,
                available=True,
                table_size=4,
                wait_minutes=0,
                tags=["elder_friendly", "light_food", "proper_meal", "group_table"],
            ),
        ]

        ranked = PlanningEngine(MockLocalLifeProvider())._rank_restaurant_candidates(restaurants, context)

        self.assertEqual("清和小馆", ranked[0].name)


class PlanningStrategyTest(unittest.TestCase):
    def test_persona_strategy_adds_elder_stroll_rules(self) -> None:
        intent = ParticipantConstraintBuilder().normalize(
            IntentParser().parse("陪爸妈附近走走，别太累，晚饭清淡一点。")
        )

        strategy = PersonaStrategyBuilder().build(intent)

        self.assertEqual("elder_stroll_light_meal", strategy.name)
        self.assertIn("stroll_friendly", strategy.preferred_activity_tags)
        self.assertIn("proper_meal", strategy.preferred_restaurant_tags)
        self.assertIn("amenity:library", strategy.avoid_activity_categories)
        self.assertIn("beverage_only", strategy.avoid_restaurant_tags)

    def test_longcat_strategy_builder_merges_ai_strategy_with_baseline(self) -> None:
        intent = ParticipantConstraintBuilder().normalize(
            IntentParser().parse("陪爸妈附近走走，别太累，晚饭清淡一点。")
        )
        client = StubLongCatClient(
            content=json.dumps(
                {
                    "name": "ai_elder_stroll",
                    "summary": "AI 认为应优先公园慢走和清淡正餐",
                    "preferred_activity_tags": ["stroll_friendly", "park"],
                    "preferred_restaurant_tags": ["proper_meal", "light_food"],
                    "avoid_restaurant_tags": ["beverage_only", "heavy_food"],
                    "reasoning": ["爸妈场景重在可休息和少走路"],
                },
                ensure_ascii=False,
            )
        )

        strategy = LongCatStrategyBuilder(PersonaStrategyBuilder(), client).build(intent)

        self.assertEqual("ai_elder_stroll", strategy.name)
        self.assertIn("stroll_friendly", strategy.preferred_activity_tags)
        self.assertIn("proper_meal", strategy.preferred_restaurant_tags)
        self.assertIn("amenity:library", strategy.avoid_activity_categories)
        self.assertIn("heavy_food", strategy.avoid_restaurant_tags)

    def test_pet_plan_allows_pet_possible_restaurant_with_warning(self) -> None:
        intent = IntentParser().parse("下午带狗出去玩，顺便找个能带宠物的地方吃饭。")
        context = ContextBuilder().build(ParticipantConstraintBuilder().normalize(intent), USER_CONTEXT)
        self.assertNotIsInstance(context, dict)

        plan = PlanningEngine(PetPossibleProvider()).generate_plan(context)

        self.assertNotEqual("需要补充或放宽条件", plan.title)
        self.assertIn("宠物公园", plan.title)
        self.assertTrue(any("必须电话确认" in note for note in plan.risk_notes))

    def test_pet_plan_uses_takeaway_when_restaurant_pet_policy_is_unknown(self) -> None:
        intent = IntentParser().parse("下午带狗出去玩，顺便找个能带宠物的地方吃饭。")
        context = ContextBuilder().build(ParticipantConstraintBuilder().normalize(intent), USER_CONTEXT)
        self.assertNotIsInstance(context, dict)

        plan = PlanningEngine(PetTakeawayProvider()).generate_plan(context)

        self.assertNotEqual("需要补充或放宽条件", plan.title)
        self.assertGreaterEqual(len(plan.schedule), 4)
        self.assertTrue(any("打包" in note or "外带" in note for note in plan.risk_notes))
        restaurant_item = next(item for item in plan.schedule if item.type == "restaurant")
        self.assertIn("外带", restaurant_item.reason)


class MeituanHandoffTest(unittest.TestCase):
    def test_meituan_link_uses_city_restaurant_and_location(self) -> None:
        intent = IntentParser().parse("陪爸妈附近走走，别太累，晚饭清淡一点。")
        context = ContextBuilder().build(
            ParticipantConstraintBuilder().normalize(intent),
            {
                **USER_CONTEXT,
                "district": "朝阳区",
            },
        )
        self.assertNotIsInstance(context, dict)
        restaurant = Restaurant(
            restaurant_id="restaurant_real_001",
            name="清禾小馆",
            location="望湖公园商业街",
            coordinates=Coordinates(39.992, 116.477),
            distance_km=0.4,
            available=True,
            table_size=4,
            wait_minutes=0,
            tags=["proper_meal", "light_food"],
            reservation_required=False,
            provider="osm_overpass",
        )

        link = HandoffLinkBuilder().restaurant_search(restaurant, context)

        self.assertEqual("multi", link["provider"])
        self.assertIn("北京 朝阳区 清禾小馆 望湖公园商业街", link["query"])
        self.assertTrue(link["url"].startswith("https://www.meituan.com/s/"))
        self.assertEqual(3, len(link["links"]))
        platforms = {item["platform"] for item in link["links"]}
        self.assertIn("meituan_app", platforms)
        self.assertIn("dianping_app", platforms)
        self.assertIn("meituan_web", platforms)

    def test_real_restaurant_plan_includes_meituan_handoff_action(self) -> None:
        intent = IntentParser().parse("下午带狗出去玩，顺便找个能带宠物的地方吃饭。")
        context = ContextBuilder().build(ParticipantConstraintBuilder().normalize(intent), USER_CONTEXT)
        self.assertNotIsInstance(context, dict)

        plan = PlanningEngine(PetPossibleProvider()).generate_plan(context)
        reserve_action = next(action for action in plan.pending_actions if action.type == "reserve_restaurant")

        self.assertEqual("multi", reserve_action.payload["handoff_provider"])
        self.assertIn("露台咖啡", reserve_action.payload["handoff_query"])
        self.assertTrue(str(reserve_action.payload["handoff_url"]).startswith("https://www.meituan.com/s/"))
        self.assertIsInstance(reserve_action.payload["handoff_links"], list)
        self.assertTrue(len(reserve_action.payload["handoff_links"]) >= 2)

    def test_real_provider_returns_meituan_handoff_instead_of_fake_booking(self) -> None:
        provider = OpenStreetMapLocalLifeProvider()

        result = provider.reserve_restaurant(
            "restaurant_real_001",
            {
                "handoff_provider": "multi",
                "handoff_url": "https://www.meituan.com/s/%E6%B8%85%E7%A6%BE%E5%B0%8F%E9%A6%86",
                "handoff_label": "去预订",
                "handoff_links": [
                    {"platform": "meituan_app", "label": "美团 App", "url": "imeituan://www.meituan.com/s/test"},
                    {"platform": "meituan_web", "label": "美团网页", "url": "https://www.meituan.com/s/test"},
                ],
                "handoff_query": "北京 清禾小馆",
            },
        )

        self.assertTrue(result["handoff_required"])
        self.assertEqual("multi", result["handoff_provider"])
        self.assertEqual(2, len(result["handoff_links"]))

    def test_executor_treats_meituan_handoff_as_completed(self) -> None:
        intent = IntentParser().parse("下午带狗出去玩，顺便找个能带宠物的地方吃饭。")
        context = ContextBuilder().build(ParticipantConstraintBuilder().normalize(intent), USER_CONTEXT)
        self.assertNotIsInstance(context, dict)
        plan = PlanningEngine(PetPossibleProvider()).generate_plan(context)

        result = ExecutionManager(OpenStreetMapLocalLifeProvider()).execute(plan)

        self.assertEqual("completed", result.execution_status)
        self.assertTrue(any(item.get("handoff_required") for item in result.results))


class CandidateSelectorTest(unittest.TestCase):
    def test_longcat_candidate_selector_chooses_real_candidate_option(self) -> None:
        intent = ParticipantConstraintBuilder().normalize(IntentParser().parse("陪爸妈附近走走，别太累，晚饭清淡一点。"))
        context = ContextBuilder().build(intent, USER_CONTEXT, PersonaStrategyBuilder().build(intent))
        self.assertNotIsInstance(context, dict)

        candidates = [
            (
                91.0,
                Activity(
                    activity_id="activity_library",
                    name="社区图书馆",
                    category="amenity:library",
                    location="社区",
                    coordinates=Coordinates(39.99, 116.48),
                    distance_km=0.2,
                    duration_minutes=60,
                    capacity_left=20,
                    tags=["quiet", "elder_friendly"],
                ),
                Restaurant(
                    restaurant_id="restaurant_coffee",
                    name="瑞幸咖啡",
                    location="楼下",
                    coordinates=Coordinates(39.9901, 116.4801),
                    distance_km=0.2,
                    available=True,
                    table_size=4,
                    wait_minutes=0,
                    tags=["beverage_only", "quiet"],
                ),
                RouteOption("家", "社区图书馆", "walking", 4, 0.3, 0, 0.68, 0.62),
                [RouteOption("家", "社区图书馆", "walking", 4, 0.3, 0, 0.68, 0.62)],
            ),
            (
                88.0,
                Activity(
                    activity_id="activity_garden",
                    name="街心花园",
                    category="leisure:garden",
                    location="社区",
                    coordinates=Coordinates(39.991, 116.481),
                    distance_km=1.0,
                    duration_minutes=60,
                    capacity_left=20,
                    tags=["stroll_friendly", "low_walking", "elder_friendly"],
                ),
                Restaurant(
                    restaurant_id="restaurant_light",
                    name="清禾小馆",
                    location="公园旁",
                    coordinates=Coordinates(39.9911, 116.4811),
                    distance_km=1.1,
                    available=True,
                    table_size=4,
                    wait_minutes=0,
                    tags=["proper_meal", "light_food", "elder_friendly"],
                ),
                RouteOption("家", "街心花园", "ride_hailing", 8, 1.2, 14, 0.9, 0.88),
                [RouteOption("家", "街心花园", "ride_hailing", 8, 1.2, 14, 0.9, 0.88)],
            ),
        ]
        client = StubLongCatClient(
            content=json.dumps(
                {
                    "option_id": "option_2",
                    "route_mode": "ride_hailing",
                    "reasoning": ["爸妈场景更适合低强度花园慢走和清淡正餐"],
                },
                ensure_ascii=False,
            )
        )

        decision = LongCatCandidateSelector(client).decide(context, candidates)

        self.assertEqual("option_2", decision.option_id)
        self.assertEqual("ride_hailing", decision.route_mode)
        self.assertIn("低强度", decision.reasoning[0])

    def test_planning_engine_uses_selected_candidate_as_main_plan_anchor(self) -> None:
        intent = ParticipantConstraintBuilder().normalize(IntentParser().parse("今天下午附近走走，顺便吃饭。"))
        context = ContextBuilder().build(intent, USER_CONTEXT, PersonaStrategyBuilder().build(intent))
        self.assertNotIsInstance(context, dict)
        client = StubLongCatClient(
            content=json.dumps(
                {
                    "option_id": "option_2",
                    "route_mode": "walking",
                    "reasoning": ["选择器明确偏向安静活动和安静餐厅"],
                },
                ensure_ascii=False,
            )
        )

        plan = PlanningEngine(SelectorAnchorProvider(), LongCatCandidateSelector(client)).generate_plan(context)

        activity_names = [item.name for item in plan.schedule if item.type == "activity"]
        restaurant_name = next(item.name for item in plan.schedule if item.type == "restaurant")

        self.assertEqual("模型选择活动", activity_names[0])
        self.assertEqual("模型选择餐厅", restaurant_name)
        self.assertIn("安静活动", plan.selection_reasoning[0])


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
                "mode": "mock",
                "user_context": USER_CONTEXT,
            }
        )
        self.assertTrue(response["success"])
        self.assertIn("plan_id", response["data"])

    def test_agent_falls_back_when_longcat_fails(self) -> None:
        response = LocalPlannerAgent(llm_client=RaisingLongCatClient()).plan(
            {
                "message": "下午带狗出去玩，顺便找个能带宠物的地方吃饭。",
                "mode": "mock",
                "user_context": USER_CONTEXT,
            }
        )
        self.assertTrue(response["success"])
        self.assertIn("plan_id", response["data"])

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

    def test_longcat_intent_parser_preserves_rule_based_elder_signals(self) -> None:
        client = StubLongCatClient(
            content="""
            {
              "start_time": "16:00",
              "end_time": "20:00",
              "radius_km": 4,
              "preferences": ["nearby", "low_walking"],
              "scenario_tags": ["elder"],
              "participants": [{"relation": "elder", "count": 2}]
            }
            """
        )
        intent = LongCatIntentParser(IntentParser(), client).parse("陪爸妈附近走走，别太累，晚饭清淡一点。")
        self.assertIn("stroll", intent.preferences)
        self.assertIn("proper_meal", intent.preferences)
        self.assertIn("light_food", intent.preferences)
        self.assertIn("elder", intent.scenario_tags)

    def test_longcat_response_generator_uses_model_content(self) -> None:
        client = SequencedLongCatClient(
            [
                json.dumps(to_intent_payload(IntentParser().parse("下午和恋人约会，想有点仪式感。")), ensure_ascii=False),
                json.dumps(
                    {
                        "name": "date_atmosphere_plan",
                        "summary": "约会优先氛围和低打扰",
                        "preferred_activity_tags": ["date", "quiet"],
                        "preferred_restaurant_tags": ["date", "proper_meal"],
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "option_id": "option_1",
                        "route_mode": "ride_hailing",
                        "reasoning": ["在真实候选中优先选择约会氛围和低打扰组合"],
                    },
                    ensure_ascii=False,
                ),
                "15:00 出发，先活动再吃饭，确认后我来预约。",
            ]
        )
        agent = LocalPlannerAgent(llm_client=client, default_mode="mock")
        planned = agent.plan({"message": "下午和恋人约会，想有点仪式感。", "user_context": USER_CONTEXT})
        self.assertTrue(planned["success"], planned)
        self.assertEqual("15:00 出发，先活动再吃饭，确认后我来预约。", planned["data"]["final_message"])

    def test_longcat_response_generator_returns_fallback_on_error(self) -> None:
        generator = LongCatResponseGenerator(ResponseGenerator(), RaisingLongCatClient())
        agent = test_agent()
        context = agent.context_builder.build(IntentParser().parse("下午和恋人约会。"), USER_CONTEXT)
        self.assertNotIsInstance(context, dict)
        plan = agent.planner.generate_plan(context)
        result = generator.summarize_plan(plan)
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)


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
            payload = to_intent_payload(intent)
            fallback_participants = (request.get("fallback_reference") or {}).get("participants")
            if fallback_participants:
                payload["participants"] = fallback_participants
            return json.dumps(payload, ensure_ascii=False)
        if "策略规划器" in messages[0]["content"]:
            request = json.loads(messages[-1]["content"])
            return json.dumps(request.get("fallback_strategy", {}), ensure_ascii=False)
        if "候选决策器" in messages[0]["content"]:
            request = json.loads(messages[-1]["content"])
            option = request["candidate_options"][0]
            return json.dumps(
                {
                    "option_id": option["option_id"],
                    "route_mode": option["default_route_mode"],
                    "reasoning": ["从真实候选中选择规则得分最高且符合画像的一组"],
                },
                ensure_ascii=False,
            )
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


class PetPossibleProvider:
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
                activity_id="activity_pet_001",
                name="宠物公园",
                category="leisure:park",
                location="附近公园",
                coordinates=Coordinates(39.99, 116.48),
                distance_km=1.1,
                duration_minutes=75,
                capacity_left=30,
                tags=["pet_friendly", "outdoor", "low_walking"],
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
                restaurant_id="restaurant_pet_possible_001",
                name="露台咖啡",
                location="公园旁",
                coordinates=Coordinates(39.991, 116.481),
                distance_km=1.2,
                available=True,
                table_size=4,
                wait_minutes=0,
                tags=["pet_possible", "outdoor", "group_table", "afternoon_tea"],
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
                mode="walking",
                duration_minutes=12,
                distance_km=1.1,
                estimated_cost=0,
                comfort_score=0.72,
                kid_friendly_score=0.6,
                walking_minutes=12,
            )
        ]

    def book_activity(self, activity_id: str, payload: dict) -> dict:
        return {"status": "ready"}

    def reserve_restaurant(self, restaurant_id: str, payload: dict) -> dict:
        return {"status": "ready"}

    def send_notification(self, payload: dict) -> dict:
        return {"status": "ready"}


class PetTakeawayProvider(PetPossibleProvider):
    def search_restaurants(
        self,
        tags: list[str],
        party_size: int,
        radius_km: float,
        origin: Coordinates | None = None,
    ) -> list[Restaurant]:
        return [
            Restaurant(
                restaurant_id="restaurant_takeaway_001",
                name="公园旁小馆",
                location="公园旁",
                coordinates=Coordinates(39.991, 116.481),
                distance_km=1.2,
                available=True,
                table_size=4,
                wait_minutes=0,
                tags=["proper_meal", "takeaway_possible", "group_table"],
                reservation_required=False,
                average_price=80,
                provider=self.provider_name,
            )
        ]


class SelectorAnchorProvider:
    provider_name = "mock"

    def search_activities(
        self,
        tags: list[str],
        party_size: int,
        radius_km: float,
        origin: Coordinates | None = None,
    ) -> list[Activity]:
        return [
            Activity(
                activity_id="activity_rule_top",
                name="规则高分活动",
                category="light_walk",
                location="楼下广场",
                coordinates=Coordinates(39.996, 116.482),
                distance_km=0.4,
                duration_minutes=70,
                capacity_left=20,
                tags=["stroll_friendly", "low_walking", "outdoor"],
            ),
            Activity(
                activity_id="activity_selector_choice",
                name="模型选择活动",
                category="quiet_space",
                location="安静空间",
                coordinates=Coordinates(39.99, 116.49),
                distance_km=3.0,
                duration_minutes=70,
                capacity_left=20,
                tags=["quiet"],
            ),
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
                restaurant_id="restaurant_rule_top",
                name="规则高分餐厅",
                location="楼下餐厅",
                coordinates=Coordinates(39.9961, 116.4821),
                distance_km=0.4,
                available=True,
                table_size=8,
                wait_minutes=0,
                tags=["proper_meal", "group_table"],
            ),
            Restaurant(
                restaurant_id="restaurant_selector_choice",
                name="模型选择餐厅",
                location="安静餐厅",
                coordinates=Coordinates(39.9902, 116.4902),
                distance_km=3.1,
                available=True,
                table_size=8,
                wait_minutes=0,
                tags=["quiet"],
            ),
        ]

    def calculate_routes(
        self,
        origin_name: str,
        origin: Coordinates,
        destination_name: str,
        destination: Coordinates,
        modes: list[str],
    ) -> list[RouteOption]:
        distance = max(abs(origin.lat - destination.lat) * 111 + abs(origin.lng - destination.lng) * 85, 0.5)
        return [
            RouteOption(
                from_name=origin_name,
                to_name=destination_name,
                mode="walking",
                duration_minutes=max(5, round(distance * 8)),
                distance_km=round(distance, 1),
                estimated_cost=0,
                comfort_score=0.75,
                kid_friendly_score=0.7,
                route_geometry=[origin, destination],
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


def schedule_span_minutes(schedule: list[dict]) -> int:
    def to_minutes(value: str) -> int:
        hour, minute = value.split(":")
        return int(hour) * 60 + int(minute)

    if not schedule:
        return 0
    delta = to_minutes(schedule[-1]["end_time"]) - to_minutes(schedule[0]["start_time"])
    return delta if delta >= 0 else delta + 24 * 60


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

    def test_parses_elder_stroll_and_dinner_intent(self) -> None:
        intent = IntentParser().parse("陪爸妈附近走走，别太累，晚饭清淡一点。")
        self.assertIn("elder", {participant.relation for participant in intent.participants})
        self.assertIn("stroll", intent.preferences)
        self.assertIn("proper_meal", intent.preferences)
        self.assertIn("light_food", [constraint.value for participant in intent.participants for constraint in participant.constraints])

    def test_explicit_companions_are_merged_and_normalized(self) -> None:
        intent = IntentParser().parse(
            "今天下午附近走走，顺便吃饭。",
            [{"name": "Lily", "relation": "闺蜜"}],
        )
        relations = {participant.relation for participant in intent.participants}

        self.assertIn("self", relations)
        self.assertIn("bestie", relations)
        self.assertIn("bestie", intent.scenario_tags)

    def test_total_friend_party_count_includes_self(self) -> None:
        intent = IntentParser().parse("今天下午和朋友出去玩，总共4个人，2男2女，安排4-6小时")

        self.assertEqual(4, intent.party_size)
        friend_group = next(participant for participant in intent.participants if participant.relation == "friend_group")
        self.assertEqual(3, friend_group.count)

    def test_explicit_friend_count_excludes_self(self) -> None:
        intent = IntentParser().parse("今天下午和4个朋友出去玩，安排4-6小时")

        self.assertEqual(5, intent.party_size)
        friend_group = next(participant for participant in intent.participants if participant.relation == "friend_group")
        self.assertEqual(4, friend_group.count)


class LocalPlannerAgentTest(unittest.TestCase):
    def test_competition_mock_plans_are_at_least_four_hours(self) -> None:
        agent = LocalPlannerAgent(
            llm_client=LongCatClient(
                LongCatConfig(api_key=None, base_url="https://api.longcat.chat", model="LongCat-Flash-Chat")
            ),
            default_mode="mock",
        )
        scenarios = [
            ("今天下午想和老婆孩子、朋友出去玩几个小时，别离家太远，老婆最近在减肥，孩子5岁", 7),
            ("今天下午和朋友出去玩，总共4个人，2男2女，安排4-6小时", 4),
        ]

        for message, expected_party_size in scenarios:
            with self.subTest(message=message):
                response = agent.plan({"message": message, "mode": "mock", "user_context": USER_CONTEXT})

                self.assertTrue(response["success"], response)
                schedule = response["data"]["schedule"]
                span = schedule_span_minutes(schedule)

                self.assertGreaterEqual(span, 240)
                self.assertLessEqual(span, 360)
                activity_starts = {item["name"]: item["start_time"] for item in schedule if item["type"] == "activity"}
                for action in response["data"]["pending_actions"]:
                    if action["type"] == "book_activity":
                        self.assertEqual(activity_starts[action["target"]], action["payload"]["start_time"])
                    if "party_size" in action["payload"]:
                        self.assertEqual(expected_party_size, action["payload"]["party_size"])

    def test_child_constraints_are_preferences_when_real_tags_are_sparse(self) -> None:
        intent = IntentParser().parse("下午和老婆孩子、朋友出去玩几个小时，别离家太远。")
        intent = ParticipantConstraintBuilder().normalize(intent)
        context = ContextBuilder().build(intent, USER_CONTEXT)
        self.assertNotIsInstance(context, dict)

        plan = PlanningEngine(SparseRealTagProvider()).generate_plan(context)

        self.assertNotEqual("需要补充或放宽条件", plan.title)
        self.assertGreaterEqual(len(plan.schedule), 4)
        self.assertFalse(any("来自真实地图 POI" in item.reason for item in plan.schedule))
        self.assertTrue(any("儿童需求已作为强偏好" in note for note in plan.risk_notes))
        self.assertTrue(any("POI 数量偏少" in note or "标签较少" in note for note in plan.risk_notes))

    def test_generated_plan_includes_route_geometry_for_map(self) -> None:
        intent = IntentParser().parse("陪爸妈附近走走，别太累，晚饭清淡一点。")
        context = ContextBuilder().build(ParticipantConstraintBuilder().normalize(intent), USER_CONTEXT)
        self.assertNotIsInstance(context, dict)

        plan = PlanningEngine(MockLocalLifeProvider()).generate_plan(context)
        travel_items = [item for item in plan.schedule if item.type == "travel"]

        self.assertTrue(travel_items)
        self.assertTrue(all(len(item.route_geometry) >= 2 for item in travel_items))

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

    def test_companions_drive_planning_when_message_is_generic(self) -> None:
        agent = test_agent()
        bestie_plan = agent.plan(
            {
                "message": "今天下午附近走走，顺便吃饭。",
                "user_context": USER_CONTEXT,
                "companions": [{"name": "Lily", "relation": "闺蜜", "contact_value": "lily@example.com"}],
            }
        )
        pet_plan = agent.plan(
            {
                "message": "今天下午附近走走，顺便吃饭。",
                "user_context": USER_CONTEXT,
                "companions": [{"name": "小狗", "relation": "宠物", "contact_value": ""}],
            }
        )

        self.assertTrue(bestie_plan["success"], bestie_plan)
        self.assertTrue(pet_plan["success"], pet_plan)
        self.assertNotEqual(bestie_plan["data"]["title"], pet_plan["data"]["title"])
        self.assertIn("闺蜜", " ".join(bestie_plan["data"]["participant_summary"]))
        self.assertIn("宠物", " ".join(pet_plan["data"]["participant_summary"]))

    def test_plan_includes_weighted_alternative_strategies(self) -> None:
        agent = test_agent()
        response = agent.plan(
            {
                "message": "今天下午附近走走，顺便吃饭。",
                "user_context": USER_CONTEXT,
                "companions": [{"name": "Lily", "relation": "闺蜜", "contact_value": "lily@example.com"}],
            }
        )

        self.assertTrue(response["success"], response)
        alternatives = response["data"]["alternatives"]
        strategies = {item["strategy"] for item in alternatives}

        self.assertIn("place_first", strategies)
        self.assertIn("distance_first", strategies)
        self.assertTrue(all("score_parts" in item for item in alternatives))
        self.assertTrue(all("tradeoff" in item for item in alternatives))
        self.assertTrue(all(item.get("plan", {}).get("plan_id") for item in alternatives))

    def test_weighted_alternative_plan_can_be_confirmed(self) -> None:
        agent = test_agent()
        response = agent.plan(
            {
                "message": "今天下午附近走走，顺便吃饭。",
                "user_context": USER_CONTEXT,
                "companions": [{"name": "Lily", "relation": "闺蜜", "contact_value": "lily@example.com"}],
            }
        )
        alternative_plan = response["data"]["alternatives"][0]["plan"]
        confirmed = agent.confirm(
            {
                "plan_id": alternative_plan["plan_id"],
                "selected_route_mode": alternative_plan["route_options"][0]["mode"],
                "confirmed_action_ids": [item["action_id"] for item in alternative_plan["pending_actions"]],
            }
        )

        self.assertTrue(confirmed["success"], confirmed)
        self.assertEqual(alternative_plan["plan_id"], confirmed["data"]["plan_id"])

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
        activity_starts = {item.name: item.start_time for item in stored.schedule if item.type == "activity"}
        restaurant = next(item for item in stored.schedule if item.type == "restaurant")
        for action in stored.pending_actions:
            if action.type == "book_activity":
                self.assertEqual(activity_starts[action.target], action.payload["start_time"])
            if action.type == "reserve_restaurant":
                self.assertEqual(restaurant.start_time, action.payload["arrival_time"])

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
