from __future__ import annotations

import json
from json import JSONDecodeError
from math import atan2, ceil, cos, radians, sin, sqrt
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.domain.enums import TransportMode
from app.domain.models import Activity, Coordinates, Restaurant, RouteOption
from app.providers.base import ProviderAPIError


class OpenStreetMapLocalLifeProvider:
    provider_name = "osm_overpass"
    overpass_endpoint = "https://overpass-api.de/api/interpreter"
    osrm_endpoint = "https://router.project-osrm.org/route/v1"
    user_agent = "NearNowLocalPlanner/0.1"

    def __init__(self, timeout_seconds: float = 8.0, max_results: int = 10) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_results = max_results

    def search_activities(
        self,
        tags: list[str],
        party_size: int,
        radius_km: float,
        origin: Coordinates | None = None,
    ) -> list[Activity]:
        origin = self._require_origin(origin)
        payload = self._fetch_overpass(self._activity_query(tags, radius_km, origin))
        return self.from_overpass_activities_payload(payload, tags, party_size, origin)

    def search_restaurants(
        self,
        tags: list[str],
        party_size: int,
        radius_km: float,
        origin: Coordinates | None = None,
    ) -> list[Restaurant]:
        origin = self._require_origin(origin)
        payload = self._fetch_overpass(self._restaurant_query(radius_km, origin))
        return self.from_overpass_restaurants_payload(payload, tags, party_size, origin)

    def calculate_routes(
        self,
        origin_name: str,
        origin: Coordinates,
        destination_name: str,
        destination: Coordinates,
        modes: list[str],
    ) -> list[RouteOption]:
        options: list[RouteOption] = []
        failures: list[str] = []
        for mode in modes:
            profiles = self._osrm_profiles_for_mode(mode)
            if not profiles:
                continue
            for profile in profiles:
                try:
                    payload = self._fetch_osrm_route(profile, origin, destination)
                    options.append(self.from_osrm_payload(payload, origin_name, destination_name, mode))
                    break
                except ProviderAPIError as exc:
                    failures.append(f"{mode}:{profile}:{exc}")

        if not options:
            detail = "; ".join(failures[-3:]) or "no supported route profile"
            raise ProviderAPIError(f"真实路线规划失败：{detail}")
        return options

    def book_activity(self, activity_id: str, payload: dict) -> dict:
        raise ProviderAPIError("真实活动预约接口尚未配置，无法自动预约。")

    def reserve_restaurant(self, restaurant_id: str, payload: dict) -> dict:
        raise ProviderAPIError("真实餐厅订座接口尚未配置，无法自动订座。")

    def send_notification(self, payload: dict) -> dict:
        return {"message_id": "local_plan_ready", "status": "ready_to_send"}

    def from_overpass_activities_payload(
        self,
        payload: dict,
        scenario_tags: list[str],
        party_size: int,
        origin: Coordinates,
    ) -> list[Activity]:
        activities: list[Activity] = []
        seen: set[str] = set()
        for element in payload.get("elements", []):
            place = self._place_from_element(element)
            if place is None:
                continue
            tags = place["tags"]
            name = self._name(tags)
            if not name:
                continue

            place_id = self._place_id("activity", element)
            if place_id in seen:
                continue
            seen.add(place_id)

            coordinates = place["coordinates"]
            distance = self._distance_km(origin, coordinates)
            item_tags = self._activity_tags(tags, scenario_tags)
            activities.append(
                Activity(
                    activity_id=place_id,
                    name=name,
                    category=self._category(tags),
                    location=self._location(tags, name),
                    coordinates=coordinates,
                    distance_km=round(distance, 2),
                    duration_minutes=self._activity_duration(tags),
                    capacity_left=max(20, party_size),
                    tags=sorted(item_tags),
                    reservation_required=False,
                    provider=self.provider_name,
                    provider_place_id=place_id,
                )
            )

        activities.sort(key=lambda item: (item.distance_km, item.name))
        return activities[: self.max_results]

    def from_overpass_restaurants_payload(
        self,
        payload: dict,
        scenario_tags: list[str],
        party_size: int,
        origin: Coordinates,
    ) -> list[Restaurant]:
        restaurants: list[Restaurant] = []
        seen: set[str] = set()
        for element in payload.get("elements", []):
            place = self._place_from_element(element)
            if place is None:
                continue
            tags = place["tags"]
            name = self._name(tags)
            if not name:
                continue

            place_id = self._place_id("restaurant", element)
            if place_id in seen:
                continue
            seen.add(place_id)

            coordinates = place["coordinates"]
            restaurants.append(
                Restaurant(
                    restaurant_id=place_id,
                    name=name,
                    location=self._location(tags, name),
                    coordinates=coordinates,
                    distance_km=round(self._distance_km(origin, coordinates), 2),
                    available=True,
                    table_size=max(6, party_size),
                    wait_minutes=0,
                    tags=sorted(self._restaurant_tags(tags, scenario_tags)),
                    reservation_required=False,
                    average_price=0,
                    provider=self.provider_name,
                    provider_place_id=place_id,
                )
            )

        restaurants.sort(key=lambda item: (item.distance_km, item.name))
        return restaurants[: self.max_results]

    def from_osrm_payload(
        self,
        payload: dict,
        origin_name: str,
        destination_name: str,
        mode: str,
    ) -> RouteOption:
        if payload.get("code") != "Ok":
            raise ProviderAPIError(f"OSRM 返回异常状态：{payload.get('code') or 'unknown'}")
        try:
            route = payload["routes"][0]
            distance_km = float(route["distance"]) / 1000
            duration_minutes = max(3, ceil(float(route["duration"]) / 60))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderAPIError("OSRM 路线结果缺少距离或耗时。") from exc

        return RouteOption(
            from_name=origin_name,
            to_name=destination_name,
            mode=str(mode),
            duration_minutes=duration_minutes,
            distance_km=round(distance_km, 1),
            estimated_cost=self._estimated_route_cost(mode, distance_km),
            comfort_score=self._comfort_score(mode),
            kid_friendly_score=self._kid_friendly_score(mode),
            traffic_risk="medium" if str(mode) in {TransportMode.DRIVING.value, TransportMode.RIDE_HAILING.value} else "low",
            walking_minutes=duration_minutes if str(mode) == TransportMode.WALKING.value else min(12, max(3, round(distance_km * 1.8))),
            transfer_count=0,
        )

    def _activity_query(self, tags: list[str], radius_km: float, origin: Coordinates) -> str:
        filters = self._activity_filters(tags)
        return self._overpass_query(filters, radius_km, origin)

    def _restaurant_query(self, radius_km: float, origin: Coordinates) -> str:
        filters = [
            ("amenity", "restaurant"),
            ("amenity", "cafe"),
            ("amenity", "fast_food"),
            ("amenity", "food_court"),
            ("amenity", "pub"),
            ("amenity", "bar"),
        ]
        return self._overpass_query(filters, radius_km, origin)

    def _overpass_query(self, filters: list[tuple[str, str]], radius_km: float, origin: Coordinates) -> str:
        radius_m = int(max(1000, radius_km * 1000))
        clauses = []
        for key, value in filters:
            for element_type in ("node", "way", "relation"):
                clauses.append(
                    f'{element_type}(around:{radius_m},{origin.lat:.5f},{origin.lng:.5f})["{key}"="{value}"];'
                )
        body = "\n  ".join(clauses)
        return f"[out:json][timeout:8];\n(\n  {body}\n);\nout center {self.max_results * 3};"

    def _activity_filters(self, tags: list[str]) -> list[tuple[str, str]]:
        base = [
            ("tourism", "attraction"),
            ("tourism", "museum"),
            ("tourism", "gallery"),
            ("amenity", "arts_centre"),
            ("amenity", "cinema"),
            ("amenity", "theatre"),
            ("leisure", "park"),
            ("leisure", "garden"),
            ("shop", "mall"),
        ]
        mapping = {
            "child": [
                ("leisure", "playground"),
                ("tourism", "zoo"),
                ("tourism", "theme_park"),
                ("amenity", "library"),
            ],
            "kid_friendly": [
                ("leisure", "playground"),
                ("tourism", "museum"),
                ("amenity", "library"),
            ],
            "pet": [
                ("leisure", "park"),
                ("leisure", "dog_park"),
                ("amenity", "dog_park"),
            ],
            "pet_friendly": [
                ("leisure", "park"),
                ("leisure", "dog_park"),
                ("amenity", "dog_park"),
            ],
            "elder": [
                ("leisure", "park"),
                ("leisure", "garden"),
                ("amenity", "library"),
                ("tourism", "museum"),
            ],
            "bestie": [
                ("amenity", "cafe"),
                ("tourism", "gallery"),
                ("shop", "mall"),
            ],
            "afternoon_tea": [
                ("amenity", "cafe"),
                ("shop", "mall"),
            ],
            "photo_friendly": [
                ("tourism", "gallery"),
                ("tourism", "attraction"),
                ("shop", "mall"),
                ("leisure", "park"),
            ],
            "date": [
                ("tourism", "gallery"),
                ("amenity", "cinema"),
                ("amenity", "theatre"),
                ("leisure", "park"),
            ],
            "partner": [
                ("tourism", "gallery"),
                ("amenity", "cinema"),
                ("amenity", "theatre"),
                ("leisure", "park"),
            ],
            "friend_group": [
                ("shop", "mall"),
                ("leisure", "sports_centre"),
                ("amenity", "cinema"),
                ("amenity", "community_centre"),
            ],
            "colleague": [
                ("amenity", "community_centre"),
                ("leisure", "sports_centre"),
                ("shop", "mall"),
            ],
            "team_building": [
                ("amenity", "community_centre"),
                ("leisure", "sports_centre"),
                ("shop", "mall"),
            ],
            "exhibition": [
                ("tourism", "gallery"),
                ("tourism", "museum"),
                ("amenity", "arts_centre"),
            ],
        }
        filters = list(base)
        for tag in tags:
            filters.extend(mapping.get(tag, []))
        return self._dedupe_filters(filters)

    def _fetch_overpass(self, query: str) -> dict:
        request = Request(
            self.overpass_endpoint,
            data=urlencode({"data": query}).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                "User-Agent": self.user_agent,
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, JSONDecodeError, OSError) as exc:
            raise ProviderAPIError("Overpass API 周边搜索失败。") from exc
        if not isinstance(payload.get("elements"), list):
            raise ProviderAPIError("Overpass API 返回格式不符合预期。")
        return payload

    def _fetch_osrm_route(self, profile: str, origin: Coordinates, destination: Coordinates) -> dict:
        coordinates = f"{origin.lng:.6f},{origin.lat:.6f};{destination.lng:.6f},{destination.lat:.6f}"
        params = urlencode({"overview": "false", "alternatives": "false", "steps": "false"})
        request = Request(
            f"{self.osrm_endpoint}/{profile}/{coordinates}?{params}",
            headers={"Accept": "application/json", "User-Agent": self.user_agent},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, JSONDecodeError, OSError) as exc:
            raise ProviderAPIError("OSRM API 路线查询失败。") from exc

    def _place_from_element(self, element: dict) -> dict | None:
        tags = element.get("tags") or {}
        if not isinstance(tags, dict):
            return None
        lat = element.get("lat")
        lng = element.get("lon")
        center = element.get("center") or {}
        if lat is None or lng is None:
            lat = center.get("lat")
            lng = center.get("lon")
        try:
            return {"tags": tags, "coordinates": Coordinates(float(lat), float(lng))}
        except (TypeError, ValueError):
            return None

    def _activity_tags(self, tags: dict, scenario_tags: list[str]) -> set[str]:
        result = {"group_friendly"}
        amenity = tags.get("amenity", "")
        leisure = tags.get("leisure", "")
        tourism = tags.get("tourism", "")
        shop = tags.get("shop", "")
        if leisure in {"park", "garden", "dog_park"}:
            result.update({"outdoor", "low_walking", "pet_friendly"})
        if amenity in {"dog_park"}:
            result.update({"outdoor", "pet_friendly"})
        if leisure == "playground" or tourism in {"zoo", "theme_park"}:
            result.update({"kid_friendly", "child_safe", "outdoor"})
        if tourism in {"museum", "gallery"} or amenity in {"arts_centre", "library"}:
            result.update({"indoor", "quiet", "photo_friendly", "elder_friendly"})
        if amenity in {"cinema", "theatre"}:
            result.update({"indoor", "date", "quiet"})
        if amenity == "cafe":
            result.update({"bestie", "afternoon_tea", "chat_friendly", "quiet"})
        if shop == "mall":
            result.update({"indoor", "group_friendly", "photo_friendly", "transit_accessible"})
        if self._truthy(tags.get("dog")) or self._truthy(tags.get("dogs")) or self._truthy(tags.get("pets")):
            result.add("pet_friendly")
        result.update(set(scenario_tags) & {"bestie", "date", "partner", "friend_group", "colleague", "team_building"})
        return result

    def _restaurant_tags(self, tags: dict, scenario_tags: list[str]) -> set[str]:
        result = {"group_table"}
        amenity = tags.get("amenity", "")
        cuisine = str(tags.get("cuisine", "")).lower()
        name = self._name(tags).lower()
        if amenity == "cafe":
            result.update({"bestie", "afternoon_tea", "chat_friendly", "quiet"})
        if amenity in {"restaurant", "cafe", "food_court"}:
            result.add("elder_friendly")
        if amenity in {"bar", "pub"}:
            result.add("date")
        if any(word in cuisine or word in name for word in ("vegetarian", "vegan", "salad", "healthy", "tea", "coffee", "轻食", "素")):
            result.update({"low_calorie", "light_food"})
        if any(word in cuisine for word in ("chinese", "japanese", "korean", "asian", "noodle")):
            result.add("light_food")
        if self._truthy(tags.get("outdoor_seating")):
            result.add("outdoor")
        if self._truthy(tags.get("dog")) or self._truthy(tags.get("dogs")) or self._truthy(tags.get("pets")):
            result.update({"pet_friendly", "outdoor"})
        result.update(set(scenario_tags) & {"bestie", "date", "partner", "friend_group", "colleague"})
        return result

    def _location(self, tags: dict, fallback: str) -> str:
        full = self._clean(tags.get("addr:full"))
        if full:
            return full
        parts = [
            self._clean(tags.get("addr:city")),
            self._clean(tags.get("addr:district") or tags.get("addr:subdistrict")),
            self._clean(tags.get("addr:street")),
            self._clean(tags.get("addr:housenumber")),
        ]
        location = " ".join(part for part in parts if part)
        return location or fallback

    def _name(self, tags: dict) -> str:
        return self._clean(tags.get("name:zh") or tags.get("name:zh-Hans") or tags.get("name:en") or tags.get("name"))

    def _category(self, tags: dict) -> str:
        for key in ("tourism", "amenity", "leisure", "shop"):
            value = self._clean(tags.get(key))
            if value:
                return f"{key}:{value}"
        return "place"

    def _activity_duration(self, tags: dict) -> int:
        if tags.get("tourism") in {"museum", "gallery"} or tags.get("amenity") in {"arts_centre", "cinema", "theatre"}:
            return 90
        if tags.get("leisure") in {"park", "garden", "playground", "dog_park"}:
            return 75
        return 60

    def _osrm_profiles_for_mode(self, mode: str) -> list[str]:
        value = str(mode)
        if value == TransportMode.DRIVING.value:
            return ["driving"]
        if value == TransportMode.RIDE_HAILING.value:
            return ["driving"]
        if value == TransportMode.WALKING.value:
            return ["foot", "walking"]
        if value == TransportMode.CYCLING.value:
            return ["bike", "cycling"]
        return []

    def _estimated_route_cost(self, mode: str, distance_km: float) -> int:
        value = str(mode)
        if value in {TransportMode.WALKING.value, TransportMode.CYCLING.value}:
            return 0
        if value == TransportMode.RIDE_HAILING.value:
            return max(12, round(distance_km * 4 + 10))
        if value == TransportMode.DRIVING.value:
            return max(8, round(distance_km * 2 + 6))
        return 0

    def _comfort_score(self, mode: str) -> float:
        return {
            TransportMode.WALKING.value: 0.68,
            TransportMode.CYCLING.value: 0.62,
            TransportMode.DRIVING.value: 0.82,
            TransportMode.RIDE_HAILING.value: 0.9,
        }.get(str(mode), 0.6)

    def _kid_friendly_score(self, mode: str) -> float:
        return {
            TransportMode.WALKING.value: 0.62,
            TransportMode.CYCLING.value: 0.45,
            TransportMode.DRIVING.value: 0.84,
            TransportMode.RIDE_HAILING.value: 0.88,
        }.get(str(mode), 0.55)

    def _require_origin(self, origin: Coordinates | None) -> Coordinates:
        if origin is None:
            raise ProviderAPIError("真实周边搜索需要可用的出发坐标。")
        return origin

    def _place_id(self, prefix: str, element: dict) -> str:
        return f"{prefix}_osm_{element.get('type', 'place')}_{element.get('id', 'unknown')}"

    def _dedupe_filters(self, filters: list[tuple[str, str]]) -> list[tuple[str, str]]:
        result: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item in filters:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result

    def _truthy(self, value: object) -> bool:
        return str(value or "").lower() in {"yes", "true", "1", "designated", "permissive"}

    def _clean(self, value: object) -> str:
        return " ".join(str(value or "").split()).strip()

    def _distance_km(self, origin: Coordinates, destination: Coordinates) -> float:
        earth_radius_km = 6371.0
        lat_1 = radians(origin.lat)
        lat_2 = radians(destination.lat)
        delta_lat = radians(destination.lat - origin.lat)
        delta_lng = radians(destination.lng - origin.lng)
        a = sin(delta_lat / 2) ** 2 + cos(lat_1) * cos(lat_2) * sin(delta_lng / 2) ** 2
        return earth_radius_km * 2 * atan2(sqrt(a), sqrt(1 - a))
