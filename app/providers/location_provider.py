from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from json import JSONDecodeError
from math import atan2, cos, radians, sin, sqrt
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.domain.models import Coordinates


@dataclass
class ApproximateAddress:
    city: str
    district: str
    landmark: str
    formatted_address: str
    source: str
    precision: str
    confidence: str
    distance_km: float

    def to_dict(self) -> dict:
        return asdict(self)


class MockLocationProvider:
    provider_name = "mock_reverse_geocode"

    def __init__(self) -> None:
        self.known_areas = [
            ("北京", "朝阳区", "望京 SOHO", Coordinates(39.9957, 116.4813)),
            ("北京", "朝阳区", "星河广场", Coordinates(39.9981, 116.4812)),
            ("北京", "朝阳区", "望湖公园商圈", Coordinates(39.9915, 116.4765)),
            ("上海", "徐汇区", "徐家汇", Coordinates(31.1910, 121.4375)),
            ("杭州", "西湖区", "黄龙商圈", Coordinates(30.2735, 120.1303)),
            ("深圳", "南山区", "科技园", Coordinates(22.5405, 113.9341)),
            ("广州", "越秀区", "北京路", Coordinates(23.1291, 113.2644)),
            ("纽约", "曼哈顿", "下城", Coordinates(40.7128, -74.0060)),
            ("旧金山", "旧金山市", "Mission District", Coordinates(37.7749, -122.4194)),
        ]

    def reverse_geocode(self, coordinates: Coordinates) -> ApproximateAddress:
        city, district, landmark, area_coordinates = min(
            self.known_areas,
            key=lambda item: self._distance_km(coordinates, item[3]),
        )
        distance = self._distance_km(coordinates, area_coordinates)
        if distance > 80:
            city = "定位城市"
            district = "附近区域"
            landmark = "大概位置"

        return ApproximateAddress(
            city=city,
            district=district,
            landmark=landmark,
            formatted_address=self._format_address(city, district, landmark),
            source=self.provider_name,
            precision="approximate_area",
            confidence=self._confidence(distance),
            distance_km=round(distance, 2),
        )

    def _format_address(self, city: str, district: str, landmark: str) -> str:
        return " ".join(part for part in (city, district, landmark) if part)

    def _confidence(self, distance_km: float) -> str:
        if distance_km <= 3:
            return "high"
        if distance_km <= 20:
            return "medium"
        return "low"

    def _distance_km(self, origin: Coordinates, destination: Coordinates) -> float:
        earth_radius_km = 6371.0
        lat_1 = radians(origin.lat)
        lat_2 = radians(destination.lat)
        delta_lat = radians(destination.lat - origin.lat)
        delta_lng = radians(destination.lng - origin.lng)
        a = sin(delta_lat / 2) ** 2 + cos(lat_1) * cos(lat_2) * sin(delta_lng / 2) ** 2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        return earth_radius_km * c


class OpenStreetMapLocationProvider:
    provider_name = "osm_nominatim"
    endpoint = "https://nominatim.openstreetmap.org/reverse"

    def reverse_geocode(self, coordinates: Coordinates) -> ApproximateAddress:
        params = urlencode(
            {
                "format": "jsonv2",
                "lat": f"{coordinates.lat:.2f}",
                "lon": f"{coordinates.lng:.2f}",
                "zoom": 16,
                "addressdetails": 1,
                "accept-language": "zh-CN,zh,en",
            }
        )
        request = Request(
            f"{self.endpoint}?{params}",
            headers={
                "Accept": "application/json",
                "User-Agent": "NearNowLocalPlanner/0.1",
            },
        )
        try:
            with urlopen(request, timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, JSONDecodeError, OSError) as exc:
            raise RuntimeError("reverse geocode failed") from exc

        address = self.from_nominatim_payload(payload)
        if not address.formatted_address:
            raise RuntimeError("reverse geocode returned an empty address")
        return address

    def from_nominatim_payload(self, payload: dict) -> ApproximateAddress:
        raw_address = payload.get("address") or {}
        city = self._first(
            raw_address,
            "city",
            "town",
            "village",
            "municipality",
            "county",
            "state",
        )
        district = self._first(
            raw_address,
            "city_district",
            "district",
            "borough",
            "suburb",
            "county",
            "neighbourhood",
        )
        landmark = self._first(
            raw_address,
            "neighbourhood",
            "quarter",
            "commercial",
            "suburb",
            "road",
            "pedestrian",
            "amenity",
            "building",
        ) or str(payload.get("name") or "").strip()
        if not landmark:
            landmark = self._display_name_part(payload.get("display_name"))

        formatted = self._format_address(city, district, landmark)
        return ApproximateAddress(
            city=city or "定位城市",
            district=district or "附近区域",
            landmark=landmark or "大概位置",
            formatted_address=formatted,
            source=self.provider_name,
            precision="approximate_area",
            confidence=self._confidence(city, district, landmark),
            distance_km=0.0,
        )

    def _format_address(self, city: str, district: str, landmark: str) -> str:
        seen: set[str] = set()
        parts: list[str] = []
        for part in (city, district, landmark):
            normalized = self._clean_value(part)
            if normalized and normalized not in seen:
                parts.append(normalized)
                seen.add(normalized)
        return " ".join(parts)

    def _first(self, address: dict, *keys: str) -> str:
        for key in keys:
            value = self._clean_value(address.get(key))
            if value:
                return value
        return ""

    def _display_name_part(self, display_name: object) -> str:
        parts = [part.strip() for part in str(display_name or "").split(",") if part.strip()]
        return self._clean_value(parts[0]) if parts else ""

    def _clean_value(self, value: object) -> str:
        return " ".join(str(value or "").split(";", 1)[0].split())

    def _confidence(self, city: str, district: str, landmark: str) -> str:
        filled = sum(1 for value in (city, district, landmark) if value)
        if filled >= 3:
            return "high"
        if filled == 2:
            return "medium"
        return "low"


class HybridLocationProvider:
    def __init__(self) -> None:
        self.real_provider = OpenStreetMapLocationProvider()
        self.fallback_provider = MockLocationProvider()

    def reverse_geocode(self, coordinates: Coordinates) -> ApproximateAddress:
        try:
            return self.real_provider.reverse_geocode(coordinates)
        except RuntimeError:
            return self.fallback_provider.reverse_geocode(coordinates)
