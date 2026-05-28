from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from json import JSONDecodeError
from math import ceil
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.domain.enums import TransportMode
from app.domain.models import Activity, Coordinates, Restaurant, RouteOption
from app.providers.base import ProviderAPIError
from app.providers.location_provider import ApproximateAddress
from app.utils.geo import format_location, parse_location
from app.providers.longcat_client import load_env_files
from app.providers.real_provider import OpenStreetMapLocalLifeProvider


AMAP_PROVIDER_NAME = "amap"
AMAP_BASE_URL = "https://restapi.amap.com"
AMAP_MAX_WORKERS = 2
AMAP_MAX_RETRIES = 3
AMAP_RETRY_DELAY_SECONDS = 1.0


class AmapLocalLifeProvider(OpenStreetMapLocalLifeProvider):
    """高德地图 Web 服务 Provider.

    The class intentionally keeps the same LocalLifeProvider interface as the
    legacy OSM implementation so the planning layer can switch providers
    without knowing the upstream API shape.
    """

    provider_name = AMAP_PROVIDER_NAME

    def __init__(
        self,
        api_key: str | None = None,
        timeout_seconds: float = 5.0,
        max_results: int = 48,
        base_url: str = AMAP_BASE_URL,
    ) -> None:
        super().__init__(timeout_seconds=timeout_seconds, max_results=max_results)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def search_activities(
        self,
        tags: list[str],
        party_size: int,
        radius_km: float,
        origin: Coordinates | None = None,
    ) -> list[Activity]:
        origin = self._require_origin(origin)
        pois = self._fetch_place_pois(
            origin=origin,
            radius_km=radius_km,
            types=self._activity_types(tags),
            keywords=self._activity_keywords(tags),
        )
        activities = self.from_amap_activity_pois(pois, tags, party_size, origin)
        activities.sort(key=lambda item: self._activity_sort_key(item, tags))
        return activities[: self.max_results]

    def search_restaurants(
        self,
        tags: list[str],
        party_size: int,
        radius_km: float,
        origin: Coordinates | None = None,
    ) -> list[Restaurant]:
        origin = self._require_origin(origin)
        pois = self._fetch_place_pois(
            origin=origin,
            radius_km=radius_km,
            types="050000",
            keywords=self._restaurant_keywords(tags),
        )
        restaurants = self.from_amap_restaurant_pois(pois, tags, party_size, origin)
        restaurants.sort(key=lambda item: self._restaurant_sort_key(item, tags))
        return restaurants[: self.max_results]

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
        with ThreadPoolExecutor(max_workers=min(AMAP_MAX_WORKERS, max(1, len(modes)))) as executor:
            future_to_mode = {
                executor.submit(self._calculate_route, origin_name, origin, destination_name, destination, mode): mode
                for mode in modes
            }
            for future in as_completed(future_to_mode):
                mode = future_to_mode[future]
                try:
                    options.append(future.result())
                except ProviderAPIError as exc:
                    failures.append(f"{mode}:{exc}")

        if not options:
            detail = "; ".join(failures[-3:]) or "no supported route mode"
            raise ProviderAPIError(f"高德地图路线规划失败：{detail}")
        options.sort(key=lambda item: modes.index(item.mode) if item.mode in modes else len(modes))
        return options

    def from_amap_activity_pois(
        self,
        pois: list[dict],
        scenario_tags: list[str],
        party_size: int,
        origin: Coordinates,
    ) -> list[Activity]:
        activities: list[Activity] = []
        seen: set[str] = set()
        for poi in pois:
            place = self._place_from_poi(poi)
            if place is None:
                continue
            place_id = self._place_id("activity", poi)
            if place_id in seen:
                continue
            seen.add(place_id)

            name = place["name"]
            coordinates = place["coordinates"]
            distance = self._poi_distance_km(poi, origin, coordinates)
            activities.append(
                Activity(
                    activity_id=place_id,
                    name=name,
                    category=self._poi_category(poi),
                    location=self._poi_location(poi, name),
                    coordinates=coordinates,
                    distance_km=distance,
                    duration_minutes=self._activity_duration_from_poi(poi),
                    capacity_left=max(20, party_size),
                    tags=sorted(self._activity_tags_from_poi(poi, scenario_tags)),
                    reservation_required=False,
                    provider=self.provider_name,
                    provider_place_id=str(poi.get("id") or place_id),
                )
            )
        return activities

    def from_amap_restaurant_pois(
        self,
        pois: list[dict],
        scenario_tags: list[str],
        party_size: int,
        origin: Coordinates,
    ) -> list[Restaurant]:
        restaurants: list[Restaurant] = []
        seen: set[str] = set()
        for poi in pois:
            place = self._place_from_poi(poi)
            if place is None:
                continue
            place_id = self._place_id("restaurant", poi)
            if place_id in seen:
                continue
            seen.add(place_id)

            coordinates = place["coordinates"]
            restaurants.append(
                Restaurant(
                    restaurant_id=place_id,
                    name=place["name"],
                    location=self._poi_location(poi, place["name"]),
                    coordinates=coordinates,
                    distance_km=self._poi_distance_km(poi, origin, coordinates),
                    available=True,
                    table_size=max(6, party_size),
                    wait_minutes=0,
                    tags=sorted(self._restaurant_tags_from_poi(poi, scenario_tags)),
                    reservation_required=False,
                    average_price=self._average_price(poi),
                    provider=self.provider_name,
                    provider_place_id=str(poi.get("id") or place_id),
                )
            )
        return restaurants

    def _fetch_place_pois(
        self,
        *,
        origin: Coordinates,
        radius_km: float,
        types: str,
        keywords: list[str],
    ) -> list[dict]:
        radius_m = int(max(1000, min(radius_km * 1000, 50000)))
        merged: list[dict] = []
        seen: set[str] = set()
        queries = keywords[:3] or [""]
        if "" not in queries:
            queries.append("")

        with ThreadPoolExecutor(max_workers=min(AMAP_MAX_WORKERS, len(queries))) as executor:
            futures = [
                executor.submit(
                    self._request_json,
                    "/v3/place/around",
                    {
                        "location": format_location(origin),
                        "radius": radius_m,
                        "types": types,
                        "keywords": keyword,
                        "offset": min(25, max(1, self.max_results)),
                        "page": 1,
                        "extensions": "base",
                        "sortrule": "distance",
                    },
                    "高德地图周边搜索失败。",
                )
                for keyword in queries
            ]
            failures: list[str] = []
            for future in as_completed(futures):
                try:
                    payload = future.result()
                except ProviderAPIError as exc:
                    failures.append(str(exc))
                    continue
                pois = payload.get("pois")
                if not isinstance(pois, list):
                    raise ProviderAPIError("高德地图周边搜索返回格式不符合预期。")
                for poi in pois:
                    if not isinstance(poi, dict):
                        continue
                    key = str(poi.get("id") or poi.get("name") or "")
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    merged.append(poi)
        if not merged and failures:
            detail = "; ".join(failures[-2:])
            raise ProviderAPIError(f"高德地图周边搜索失败：{detail}")
        return merged

    def _calculate_route(
        self,
        origin_name: str,
        origin: Coordinates,
        destination_name: str,
        destination: Coordinates,
        mode: str,
    ) -> RouteOption:
        value = str(mode)
        if value in {TransportMode.DRIVING.value, TransportMode.RIDE_HAILING.value}:
            payload = self._request_json(
                "/v3/direction/driving",
                {
                    "origin": format_location(origin),
                    "destination": format_location(destination),
                    "extensions": "base",
                    "strategy": 32,
                },
                "高德地图驾车路线查询失败。",
            )
            return self._route_from_v3_path(payload, origin_name, destination_name, value)
        if value == TransportMode.WALKING.value:
            payload = self._request_json(
                "/v3/direction/walking",
                {
                    "origin": format_location(origin),
                    "destination": format_location(destination),
                },
                "高德地图步行路线查询失败。",
            )
            return self._route_from_v3_path(payload, origin_name, destination_name, value)
        if value == TransportMode.PUBLIC_TRANSIT.value:
            payload = self._request_json(
                "/v3/direction/transit/integrated",
                {
                    "origin": format_location(origin),
                    "destination": format_location(destination),
                    "city": self._route_city(origin_name),
                    "strategy": 0,
                    "extensions": "base",
                },
                "高德地图公交路线查询失败。",
            )
            return self._route_from_transit(payload, origin_name, destination_name, value)
        if value == TransportMode.CYCLING.value:
            payload = self._request_json(
                "/v4/direction/bicycling",
                {
                    "origin": format_location(origin),
                    "destination": format_location(destination),
                },
                "高德地图骑行路线查询失败。",
                status_field="errcode",
                success_value="0",
                message_fields=("errmsg", "errdetail"),
            )
            return self._route_from_bicycling(payload, origin_name, destination_name, value)
        raise ProviderAPIError(f"高德地图暂不支持交通方式：{value}")

    def _route_from_v3_path(
        self,
        payload: dict,
        origin_name: str,
        destination_name: str,
        mode: str,
    ) -> RouteOption:
        try:
            path = payload["route"]["paths"][0]
            distance_km = float(path["distance"]) / 1000
            duration_minutes = max(3, ceil(float(path["duration"]) / 60))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderAPIError("高德地图路线结果缺少距离或耗时。") from exc
        return self._route_option(origin_name, destination_name, mode, distance_km, duration_minutes, path)

    def _route_from_transit(
        self,
        payload: dict,
        origin_name: str,
        destination_name: str,
        mode: str,
    ) -> RouteOption:
        try:
            transit = payload["route"]["transits"][0]
            distance_km = float(transit.get("distance") or payload["route"].get("distance") or 0) / 1000
            duration_minutes = max(3, ceil(float(transit["duration"]) / 60))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderAPIError("高德地图公交路线结果缺少距离或耗时。") from exc
        route = self._route_option(origin_name, destination_name, mode, distance_km, duration_minutes, transit)
        try:
            route.walking_minutes = max(0, round(float(transit.get("walking_distance") or 0) / 80))
        except (TypeError, ValueError):
            route.walking_minutes = min(12, max(3, round(distance_km * 1.8)))
        route.transfer_count = self._transit_transfer_count(transit)
        return route

    def _route_from_bicycling(
        self,
        payload: dict,
        origin_name: str,
        destination_name: str,
        mode: str,
    ) -> RouteOption:
        try:
            path = payload["data"]["paths"][0]
            distance_km = float(path["distance"]) / 1000
            duration_minutes = max(3, ceil(float(path["duration"]) / 60))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderAPIError("高德地图骑行路线结果缺少距离或耗时。") from exc
        return self._route_option(origin_name, destination_name, mode, distance_km, duration_minutes, path)

    def _route_option(
        self,
        origin_name: str,
        destination_name: str,
        mode: str,
        distance_km: float,
        duration_minutes: int,
        path: dict,
    ) -> RouteOption:
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
            route_geometry=self._route_geometry_from_amap(path),
        )

    def _request_json(
        self,
        path: str,
        params: dict[str, object],
        error_message: str,
        *,
        status_field: str = "status",
        success_value: str = "1",
        message_fields: tuple[str, ...] = ("info", "infocode"),
    ) -> dict:
        import time

        clean_params = {
            key: value
            for key, value in {
                "key": self._api_key(),
                "output": "JSON",
                **params,
            }.items()
            if value not in {None, ""}
        }
        request = Request(
            f"{self.base_url}{path}?{urlencode(clean_params)}",
            headers={"Accept": "application/json"},
        )

        last_error = None
        for attempt in range(AMAP_MAX_RETRIES):
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except (HTTPError, URLError, TimeoutError, JSONDecodeError, OSError) as exc:
                raise ProviderAPIError(error_message) from exc
            if str(payload.get(status_field)) != success_value:
                message = " ".join(str(payload.get(field) or "") for field in message_fields).strip()
                full_message = f"{error_message}{' ' + message if message else ''}"
                # Check if this is a rate limit error
                if "CUQPS_HAS_EXCEEDED_THE_LIMIT" in full_message or "10021" in full_message:
                    last_error = full_message
                    if attempt < AMAP_MAX_RETRIES - 1:
                        time.sleep(AMAP_RETRY_DELAY_SECONDS * (attempt + 1))
                        continue
                raise ProviderAPIError(full_message)
            return payload
        raise ProviderAPIError(last_error or error_message)

    def _api_key(self) -> str:
        if self.api_key:
            return self.api_key
        load_env_files()
        key = (
            os.getenv("AMAP_WEB_SERVICE_KEY")
            or os.getenv("AMAP_API_KEY")
            or os.getenv("GAODE_MAP_API_KEY")
            or os.getenv("GAODE_API_KEY")
        )
        if not key:
            raise ProviderAPIError("AMAP_WEB_SERVICE_KEY 未配置，无法调用高德地图 Web 服务。")
        self.api_key = key
        return key

    def _place_from_poi(self, poi: dict) -> dict | None:
        name = self._clean(poi.get("name"))
        coordinates = parse_location(poi.get("location"))
        if not name or coordinates is None:
            return None
        return {"name": name, "coordinates": coordinates}

    def _place_id(self, prefix: str, poi: dict) -> str:
        return f"{prefix}_amap_{poi.get('id') or self._clean(poi.get('name')) or 'unknown'}"

    def _poi_category(self, poi: dict) -> str:
        return self._clean(poi.get("type")) or self._clean(poi.get("typecode")) or "place"

    def _poi_location(self, poi: dict, fallback: str) -> str:
        values: list[str] = []
        for key in ("address", "pname", "cityname", "adname"):
            value = poi.get(key)
            if isinstance(value, list):
                value = ""
            cleaned = self._clean(value)
            if cleaned and cleaned not in values:
                values.append(cleaned)
        return " ".join(values) or fallback

    def _poi_distance_km(self, poi: dict, origin: Coordinates, coordinates: Coordinates) -> float:
        try:
            distance = float(poi.get("distance")) / 1000
        except (TypeError, ValueError):
            distance = self._distance_km(origin, coordinates)
        return round(distance, 2)

    def _activity_tags_from_poi(self, poi: dict, scenario_tags: list[str]) -> set[str]:
        text = self._poi_text(poi)
        result = {"group_friendly"}
        if self._contains_any(text, "公园", "花园", "绿地", "广场", "景区", "风景名胜"):
            result.update({"outdoor", "low_walking", "pet_friendly", "elder_friendly", "stroll_friendly"})
        if self._contains_any(text, "游乐", "儿童", "亲子", "动物园", "水族馆", "科技馆"):
            result.update({"kid_friendly", "child_safe"})
        if self._contains_any(text, "博物馆", "美术馆", "展览", "画廊", "艺术", "文化馆", "图书馆"):
            result.update({"indoor", "quiet", "photo_friendly", "elder_friendly", "bestie"})
        if self._contains_any(text, "电影院", "影院", "剧院", "演出"):
            result.update({"indoor", "date", "quiet"})
        if self._contains_any(text, "商场", "购物中心", "广场", "mall"):
            result.update({"indoor", "group_friendly", "photo_friendly", "transit_accessible", "bestie", "elder_friendly", "low_walking", "stroll_friendly"})
        if self._contains_any(text, "体育", "运动", "球馆", "健身"):
            result.update({"group_friendly", "team_building"})
        if self._contains_any(text, "咖啡", "茶", "甜品"):
            result.update({"bestie", "afternoon_tea", "chat_friendly", "quiet"})
        return result

    def _restaurant_tags_from_poi(self, poi: dict, scenario_tags: list[str]) -> set[str]:
        text = self._poi_text(poi)
        result = {"group_table", "takeaway_possible"}
        if self._contains_any(text, "咖啡", "茶", "甜品", "蛋糕", "饮品"):
            result.update({"bestie", "afternoon_tea", "chat_friendly", "quiet", "beverage_only", "beverage_light"})
        else:
            result.add("proper_meal")
        if self._contains_any(text, "轻食", "沙拉", "素食", "粥", "汤", "蒸", "日料", "寿司"):
            result.update({"low_calorie", "light_food"})
        if self._contains_any(text, "面", "拉面", "米线", "馄饨", "饺子", "包子", "快餐", "便当", "盖饭"):
            result.update({"quick_meal", "casual_meal"})
        if self._contains_any(text, "火锅", "烤肉", "烧烤", "串", "麻辣", "小龙虾", "川菜", "湘菜"):
            result.add("heavy_food")
        if self._contains_any(text, "露台", "户外", "花园", "院子"):
            result.update({"outdoor", "pet_possible"})
        if self._contains_any(text, "宠物", "可携宠", "狗友好"):
            result.update({"pet_friendly", "pet_possible", "outdoor"})
        if self._contains_any(text, "酒吧", "西餐", "bistro", "餐酒"):
            result.add("date")
        if self._contains_any(text, "清真"):
            result.add("halal")
        result.add("elder_friendly")
        return result

    def _activity_types(self, tags: list[str]) -> str:
        tag_set = set(tags)
        types = ["110000", "140000", "080000", "060000"]
        if {"bestie", "afternoon_tea", "咖啡", "下午茶"} & tag_set:
            types.append("050000")
        return "|".join(dict.fromkeys(types))

    def _activity_keywords(self, tags: list[str]) -> list[str]:
        mapping = [
            ({"elder", "stroll", "low_walking", "公园", "散步"}, "公园"),
            ({"child", "kid_friendly"}, "亲子"),
            ({"pet", "pet_friendly", "遛狗"}, "公园"),
            ({"bestie", "afternoon_tea", "咖啡"}, "咖啡"),
            ({"partner", "date", "约会"}, "展览"),
            ({"friend_group", "colleague", "team_building"}, "商场"),
            ({"exhibition", "展览", "艺术"}, "展览"),
            ({"电影", "影院"}, "影院"),
        ]
        tag_set = set(tags)
        return [keyword for keys, keyword in mapping if keys & tag_set]

    def _restaurant_keywords(self, tags: list[str]) -> list[str]:
        mapping = [
            ({"elder", "proper_meal", "light_food", "清淡"}, "清淡"),
            ({"bestie", "afternoon_tea", "咖啡", "甜品"}, "咖啡"),
            ({"pet", "pet_friendly", "outdoor"}, "露台"),
            ({"partner", "date", "quiet"}, "西餐"),
            ({"child", "kid_friendly", "friend_group", "group_table"}, "餐厅"),
        ]
        tag_set = set(tags)
        return [keyword for keys, keyword in mapping if keys & tag_set]

    def _activity_duration_from_poi(self, poi: dict) -> int:
        text = self._poi_text(poi)
        if self._contains_any(text, "博物馆", "美术馆", "展览", "影院", "剧院"):
            return 90
        if self._contains_any(text, "公园", "花园", "游乐", "动物园"):
            return 75
        return 60

    def _average_price(self, poi: dict) -> int:
        biz_ext = poi.get("biz_ext") if isinstance(poi.get("biz_ext"), dict) else {}
        try:
            return int(float(biz_ext.get("cost") or 0))
        except (TypeError, ValueError):
            return 0

    def _route_geometry_from_amap(self, payload: dict) -> list[Coordinates]:
        points: list[Coordinates] = []
        for polyline in self._collect_polylines(payload):
            for pair in str(polyline or "").split(";"):
                coordinates = parse_location(pair)
                if coordinates is not None:
                    points.append(coordinates)
        return points

    def _collect_polylines(self, value: object) -> list[str]:
        polylines: list[str] = []
        if isinstance(value, dict):
            polyline = value.get("polyline")
            if isinstance(polyline, str) and polyline:
                polylines.append(polyline)
            for item in value.values():
                polylines.extend(self._collect_polylines(item))
        elif isinstance(value, list):
            for item in value:
                polylines.extend(self._collect_polylines(item))
        return polylines

    def _transit_transfer_count(self, transit: dict) -> int:
        segments = transit.get("segments")
        if not isinstance(segments, list):
            return 0
        bus_count = 0
        for segment in segments:
            if isinstance(segment, dict) and segment.get("bus"):
                bus_count += 1
        return max(0, bus_count - 1)

    def _route_city(self, origin_name: str) -> str:
        known = [
            "北京",
            "上海",
            "广州",
            "深圳",
            "杭州",
            "成都",
            "重庆",
            "天津",
            "南京",
            "苏州",
            "武汉",
            "西安",
            "厦门",
            "长沙",
            "郑州",
            "青岛",
        ]
        for city in known:
            if city in origin_name:
                return city
        return os.getenv("AMAP_DEFAULT_CITY", "北京")

    def _poi_text(self, poi: dict) -> str:
        values: list[str] = []
        for key in ("name", "type", "typecode", "address", "pname", "cityname", "adname"):
            value = poi.get(key)
            if isinstance(value, list):
                continue
            values.append(self._clean(value))
        biz_ext = poi.get("biz_ext")
        if isinstance(biz_ext, dict):
            values.extend(self._clean(value) for value in biz_ext.values())
        return " ".join(value for value in values if value).lower()

    def _contains_any(self, text: str, *needles: str) -> bool:
        lower = text.lower()
        return any(needle.lower() in lower for needle in needles)


class AmapLocationProvider:
    provider_name = "amap_geocode"

    def __init__(
        self,
        api_key: str | None = None,
        timeout_seconds: float = 5.0,
        base_url: str = AMAP_BASE_URL,
    ) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.base_url = base_url.rstrip("/")

    def reverse_geocode(self, coordinates: Coordinates) -> ApproximateAddress:
        payload = self._request_json(
            "/v3/geocode/regeo",
            {
                "location": format_location(coordinates),
                "radius": 1000,
                "extensions": "base",
            },
            "高德地图逆地理编码失败。",
        )
        return self.from_regeo_payload(payload, coordinates)

    def geocode(
        self,
        query: str,
        city: str | None = None,
        district: str | None = None,
        landmark: str | None = None,
    ) -> ApproximateAddress:
        address = self._format_query(query, city, district, landmark)
        payload = self._request_json(
            "/v3/geocode/geo",
            {
                "address": address,
                "city": city or "",
            },
            "高德地图地理编码失败。",
        )
        return self.from_geo_payload(payload, city, district, landmark)

    def from_regeo_payload(self, payload: dict, coordinates: Coordinates | None = None) -> ApproximateAddress:
        regeocode = payload.get("regeocode") if isinstance(payload.get("regeocode"), dict) else {}
        component = regeocode.get("addressComponent") if isinstance(regeocode.get("addressComponent"), dict) else {}
        city = self._component_value(component.get("city")) or self._component_value(component.get("province"))
        district = self._component_value(component.get("district"))
        landmark = (
            self._component_value(component.get("township"))
            or self._nested_component(component.get("neighborhood"), "name")
            or self._nested_component(component.get("building"), "name")
            or self._nested_component(component.get("streetNumber"), "street")
        )
        formatted = self._clean(regeocode.get("formatted_address")) or self._format_address(city, district, landmark)
        return ApproximateAddress(
            city=city or "定位城市",
            district=district or "附近区域",
            landmark=landmark or "大概位置",
            formatted_address=formatted,
            source=self.provider_name,
            precision="approximate_area",
            confidence=self._confidence(city, district, landmark),
            distance_km=0.0,
            coordinates=coordinates,
        )

    def from_geo_payload(
        self,
        payload: dict,
        city: str | None = None,
        district: str | None = None,
        landmark: str | None = None,
    ) -> ApproximateAddress:
        geocodes = payload.get("geocodes")
        if not isinstance(geocodes, list) or not geocodes:
            raise RuntimeError("geocode returned no results")
        item = geocodes[0]
        if not isinstance(item, dict):
            raise RuntimeError("geocode returned invalid payload")
        coordinates = parse_location(item.get("location"))
        if coordinates is None:
            raise RuntimeError("geocode returned invalid coordinates")

        formatted = self._clean(item.get("formatted_address"))
        parsed_city = self._component_value(item.get("city")) or self._clean(city)
        parsed_district = self._component_value(item.get("district")) or self._clean(district)
        parsed_landmark = self._clean(landmark) or self._landmark_from_address(formatted, parsed_city, parsed_district)
        return ApproximateAddress(
            city=parsed_city or "定位城市",
            district=parsed_district or "附近区域",
            landmark=parsed_landmark or "大概位置",
            formatted_address=formatted or self._format_address(parsed_city, parsed_district, parsed_landmark),
            source=self.provider_name,
            precision="approximate_area",
            confidence=self._confidence(parsed_city, parsed_district, parsed_landmark),
            distance_km=0.0,
            coordinates=coordinates,
        )

    def _request_json(self, path: str, params: dict[str, object], error_message: str) -> dict:
        clean_params = {
            key: value
            for key, value in {
                "key": self._api_key(),
                "output": "JSON",
                **params,
            }.items()
            if value not in {None, ""}
        }
        request = Request(
            f"{self.base_url}{path}?{urlencode(clean_params)}",
            headers={"Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, JSONDecodeError, OSError) as exc:
            raise RuntimeError(error_message) from exc
        if str(payload.get("status")) != "1":
            info = self._clean(payload.get("info") or payload.get("infocode"))
            raise RuntimeError(f"{error_message}{' ' + info if info else ''}")
        return payload

    def _api_key(self) -> str:
        if self.api_key:
            return self.api_key
        load_env_files()
        key = (
            os.getenv("AMAP_WEB_SERVICE_KEY")
            or os.getenv("AMAP_API_KEY")
            or os.getenv("GAODE_MAP_API_KEY")
            or os.getenv("GAODE_API_KEY")
        )
        if not key:
            raise RuntimeError("AMAP_WEB_SERVICE_KEY is not configured")
        self.api_key = key
        return key

    def _format_query(
        self,
        query: str,
        city: str | None = None,
        district: str | None = None,
        landmark: str | None = None,
    ) -> str:
        values = [self._clean(value) for value in (query, city, district, landmark)]
        result: list[str] = []
        for value in values:
            if value and value not in result:
                result.append(value)
        return " ".join(result)

    def _format_address(self, city: str, district: str, landmark: str) -> str:
        parts: list[str] = []
        for value in (city, district, landmark):
            cleaned = self._clean(value)
            if cleaned and cleaned not in parts:
                parts.append(cleaned)
        return " ".join(parts)

    def _landmark_from_address(self, formatted: str, city: str, district: str) -> str:
        result = self._clean(formatted)
        for value in (city, f"{city}市" if city else "", district):
            cleaned = self._clean(value)
            if cleaned and result.startswith(cleaned):
                result = result[len(cleaned) :].strip()
        return result

    def _nested_component(self, value: object, key: str) -> str:
        if isinstance(value, dict):
            return self._clean(value.get(key))
        return ""

    def _component_value(self, value: object) -> str:
        if isinstance(value, list):
            return ""
        return self._clean(value)

    def _confidence(self, city: str, district: str, landmark: str) -> str:
        filled = sum(1 for value in (city, district, landmark) if value)
        if filled >= 3:
            return "high"
        if filled == 2:
            return "medium"
        return "low"

    def _clean(self, value: object) -> str:
        return " ".join(str(value or "").split()).strip()
