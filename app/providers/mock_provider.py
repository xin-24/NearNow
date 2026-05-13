from __future__ import annotations

from app.domain.enums import TransportMode
from app.domain.models import Activity, Coordinates, Restaurant, RouteOption


class MockLocalLifeProvider:
    provider_name = "mock"

    def __init__(self) -> None:
        self.activities = [
            Activity(
                activity_id="activity_kid_001",
                name="城市亲子探索馆",
                category="parent_child",
                location="星河广场 3F",
                coordinates=Coordinates(39.9981, 116.4812),
                distance_km=4.2,
                duration_minutes=80,
                capacity_left=12,
                tags=["kid_friendly", "child_safe", "group_friendly", "indoor"],
                provider_place_id="mock_activity_kid_001",
            ),
            Activity(
                activity_id="activity_pet_001",
                name="森氧宠物公园",
                category="pet_outdoor",
                location="望湖公园东门",
                coordinates=Coordinates(39.9909, 116.4731),
                distance_km=3.6,
                duration_minutes=90,
                capacity_left=20,
                tags=["pet_friendly", "outdoor", "group_friendly", "low_walking"],
                provider_place_id="mock_activity_pet_001",
            ),
            Activity(
                activity_id="activity_date_001",
                name="河畔艺术展",
                category="exhibition",
                location="北岸艺术中心",
                coordinates=Coordinates(39.9998, 116.4861),
                distance_km=5.1,
                duration_minutes=75,
                capacity_left=8,
                tags=["date", "photo_friendly", "quiet", "chat_friendly", "indoor"],
                provider_place_id="mock_activity_date_001",
            ),
            Activity(
                activity_id="activity_elder_001",
                name="湖畔轻步道",
                category="light_walk",
                location="望湖公园南区",
                coordinates=Coordinates(39.9915, 116.4765),
                distance_km=3.2,
                duration_minutes=60,
                capacity_left=30,
                tags=["low_walking", "quiet", "elder_friendly", "outdoor", "pet_friendly"],
                reservation_required=False,
                provider_place_id="mock_activity_elder_001",
            ),
            Activity(
                activity_id="activity_group_001",
                name="城市手作工坊",
                category="workshop",
                location="合生汇 L4",
                coordinates=Coordinates(39.9965, 116.4921),
                distance_km=5.9,
                duration_minutes=90,
                capacity_left=16,
                tags=["group_friendly", "team_building", "photo_friendly", "indoor"],
                provider_place_id="mock_activity_group_001",
            ),
            Activity(
                activity_id="activity_bestie_001",
                name="晴窗花艺下午茶",
                category="afternoon_tea",
                location="合生汇 L2",
                coordinates=Coordinates(39.9961, 116.4911),
                distance_km=5.7,
                duration_minutes=80,
                capacity_left=6,
                tags=["bestie", "afternoon_tea", "photo_friendly", "chat_friendly", "quiet"],
                provider_place_id="mock_activity_bestie_001",
            ),
        ]

        self.restaurants = [
            Restaurant(
                restaurant_id="restaurant_light_001",
                name="绿野轻食融合菜",
                location="星河广场 5F",
                coordinates=Coordinates(39.9982, 116.4814),
                distance_km=0.2,
                available=True,
                table_size=8,
                wait_minutes=0,
                tags=["low_calorie", "light_food", "kid_friendly", "group_table"],
                average_price=118,
                provider_place_id="mock_restaurant_light_001",
            ),
            Restaurant(
                restaurant_id="restaurant_bestie_001",
                name="晴窗下午茶餐厅",
                location="合生汇 L2",
                coordinates=Coordinates(39.9962, 116.4912),
                distance_km=0.1,
                available=True,
                table_size=4,
                wait_minutes=5,
                tags=["bestie", "afternoon_tea", "photo_friendly", "quiet", "chat_friendly"],
                average_price=96,
                provider_place_id="mock_restaurant_bestie_001",
            ),
            Restaurant(
                restaurant_id="restaurant_date_001",
                name="月白小馆",
                location="北岸艺术中心 1F",
                coordinates=Coordinates(39.9995, 116.4863),
                distance_km=0.2,
                available=True,
                table_size=2,
                wait_minutes=0,
                tags=["date", "quiet", "light_food", "photo_friendly"],
                average_price=168,
                provider_place_id="mock_restaurant_date_001",
            ),
            Restaurant(
                restaurant_id="restaurant_pet_001",
                name="松木小院宠物友好餐厅",
                location="望湖公园西门",
                coordinates=Coordinates(39.991, 116.4742),
                distance_km=0.6,
                available=True,
                table_size=6,
                wait_minutes=10,
                tags=["pet_friendly", "outdoor", "group_table", "light_food"],
                average_price=128,
                provider_place_id="mock_restaurant_pet_001",
            ),
            Restaurant(
                restaurant_id="restaurant_elder_001",
                name="清禾小馆",
                location="望湖公园商业街",
                coordinates=Coordinates(39.992, 116.477),
                distance_km=0.4,
                available=True,
                table_size=8,
                wait_minutes=0,
                tags=["elder_friendly", "light_food", "quiet", "low_walking", "group_table"],
                average_price=105,
                provider_place_id="mock_restaurant_elder_001",
            ),
            Restaurant(
                restaurant_id="restaurant_group_001",
                name="合席小厨",
                location="合生汇 L5",
                coordinates=Coordinates(39.9966, 116.4923),
                distance_km=0.2,
                available=True,
                table_size=12,
                wait_minutes=15,
                tags=["group_table", "team_building", "budget_control", "transit_accessible"],
                average_price=145,
                provider_place_id="mock_restaurant_group_001",
            ),
        ]

    def search_activities(
        self,
        tags: list[str],
        party_size: int,
        radius_km: float,
        origin: Coordinates | None = None,
    ) -> list[Activity]:
        return [
            item
            for item in self.activities
            if item.capacity_left >= party_size and item.distance_km <= radius_km
        ]

    def search_restaurants(
        self,
        tags: list[str],
        party_size: int,
        radius_km: float,
        origin: Coordinates | None = None,
    ) -> list[Restaurant]:
        return [
            item
            for item in self.restaurants
            if item.available and item.table_size >= party_size and item.distance_km <= max(radius_km, 1.0)
        ]

    def calculate_routes(
        self,
        origin_name: str,
        origin: Coordinates,
        destination_name: str,
        destination: Coordinates,
        modes: list[str],
    ) -> list[RouteOption]:
        distance = max(abs(origin.lat - destination.lat) * 111 + abs(origin.lng - destination.lng) * 85, 0.6)
        options: list[RouteOption] = []
        for mode in modes:
            mode_value = str(mode)
            if mode_value == TransportMode.WALKING.value:
                options.append(self._route(origin_name, destination_name, mode, distance, 13.0, 0, 0.62, walking=True))
            elif mode_value == TransportMode.DRIVING.value:
                options.append(self._route(origin_name, destination_name, mode, distance, 3.8, 18, 0.86))
            elif mode_value == TransportMode.PUBLIC_TRANSIT.value:
                options.append(self._route(origin_name, destination_name, mode, distance, 5.8, 6, 0.67, transfers=1))
            elif mode_value == TransportMode.RIDE_HAILING.value:
                options.append(self._route(origin_name, destination_name, mode, distance, 4.0, 28, 0.9))
            elif mode_value == TransportMode.CYCLING.value:
                options.append(self._route(origin_name, destination_name, mode, distance, 7.0, 0, 0.58))
        return options

    def book_activity(self, activity_id: str, payload: dict) -> dict:
        return {
            "booking_id": f"booking_{activity_id}",
            "confirmation_no": f"A{payload.get('plan_id', '000')}",
            "status": "confirmed",
        }

    def reserve_restaurant(self, restaurant_id: str, payload: dict) -> dict:
        return {
            "booking_id": f"booking_{restaurant_id}",
            "confirmation_no": f"R{payload.get('plan_id', '000')}",
            "status": "confirmed",
        }

    def send_notification(self, payload: dict) -> dict:
        return {"message_id": "message_mock_001", "status": "sent"}

    def _route(
        self,
        from_name: str,
        to_name: str,
        mode: str,
        distance_km: float,
        minutes_per_km: float,
        cost: int,
        comfort: float,
        walking: bool = False,
        transfers: int = 0,
    ) -> RouteOption:
        duration = max(5, round(distance_km * minutes_per_km))
        return RouteOption(
            from_name=from_name,
            to_name=to_name,
            mode=str(mode),
            duration_minutes=duration,
            distance_km=round(distance_km, 1),
            estimated_cost=cost,
            comfort_score=comfort,
            kid_friendly_score=comfort if transfers == 0 else comfort - 0.1,
            traffic_risk="medium" if str(mode) == TransportMode.DRIVING.value else "low",
            walking_minutes=duration if walking else min(12, max(3, round(distance_km * 1.8))),
            transfer_count=transfers,
        )
