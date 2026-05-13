from __future__ import annotations

import json
import re
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
    coordinates: Coordinates | None = None

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
            coordinates=area_coordinates,
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
    reverse_endpoint = "https://nominatim.openstreetmap.org/reverse"
    search_endpoint = "https://nominatim.openstreetmap.org/search"

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
            f"{self.reverse_endpoint}?{params}",
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

        address = self.from_nominatim_payload(payload, coordinates)
        if not address.formatted_address:
            raise RuntimeError("reverse geocode returned an empty address")
        return address

    def geocode(
        self,
        query: str,
        city: str | None = None,
        district: str | None = None,
        landmark: str | None = None,
    ) -> ApproximateAddress:
        payload: list[dict] = []
        for params in self._geocode_candidate_params(query, city, district, landmark):
            candidate_payload = self._search(params)
            if not candidate_payload:
                continue
            if self._geocode_result_is_confident(candidate_payload[0], city, district, landmark):
                payload = candidate_payload
                break

        if not payload:
            raise RuntimeError("geocode returned no confident results")
        try:
            coordinates = Coordinates(lat=float(payload[0]["lat"]), lng=float(payload[0]["lon"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("geocode returned invalid coordinates") from exc

        address = self.from_nominatim_payload(payload[0], coordinates)
        if not address.formatted_address:
            address.formatted_address = self._format_address(address.city, address.district, address.landmark)
        return address

    def _geocode_candidate_params(
        self,
        query: str,
        city: str | None = None,
        district: str | None = None,
        landmark: str | None = None,
    ) -> list[dict[str, str | int]]:
        query = self._clean_value(query)
        city = self._clean_value(city)
        district = self._clean_value(district)
        landmark = self._clean_value(landmark)

        candidates: list[dict[str, str | int]] = []

        def add(params: dict[str, str | int]) -> None:
            key = tuple(sorted((item_key, str(item_value)) for item_key, item_value in params.items()))
            if key not in seen:
                seen.add(key)
                candidates.append(params)

        seen: set[tuple[tuple[str, str], ...]] = set()
        if query:
            add({"q": query})
            if "中国" not in query and "China" not in query:
                add({"q": f"{query} 中国"})
        if city or district or landmark:
            ordered = " ".join(part for part in (landmark, district, city, "中国") if part)
            if ordered:
                add({"q": ordered})
            structured = {
                "country": "中国",
                "city": city,
                "county": district,
                "street": landmark,
            }
            add({key: value for key, value in structured.items() if value})
            broader = " ".join(part for part in (district, city, "中国") if part)
            if broader:
                add({"q": broader})
        return candidates

    def _search(self, params: dict[str, str | int]) -> list[dict]:
        encoded = urlencode(
            {
                "format": "jsonv2",
                "limit": 1,
                "addressdetails": 1,
                "accept-language": "zh-CN,zh,en",
                **params,
            }
        )
        request = Request(
            f"{self.search_endpoint}?{encoded}",
            headers={
                "Accept": "application/json",
                "User-Agent": "NearNowLocalPlanner/0.1",
            },
        )
        try:
            with urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, JSONDecodeError, OSError) as exc:
            raise RuntimeError("geocode failed") from exc
        if not isinstance(payload, list):
            raise RuntimeError("geocode returned invalid payload")
        return payload

    def _geocode_result_is_confident(
        self,
        payload: dict,
        city: str | None = None,
        district: str | None = None,
        landmark: str | None = None,
    ) -> bool:
        city = self._clean_value(city)
        district = self._clean_value(district)
        landmark = self._clean_value(landmark)
        text = self._payload_text(payload)

        if landmark:
            return self._landmark_matches(text, landmark)
        if district:
            return district in text
        if city:
            return city in text or f"{city}市" in text
        return bool(text)

    def _landmark_matches(self, text: str, landmark: str) -> bool:
        cjk_tokens = re.findall(r"[\u4e00-\u9fff]{2,}", landmark)
        if cjk_tokens:
            return any(token in text for token in cjk_tokens)
        tokens = [token.lower() for token in re.findall(r"[A-Za-z0-9]{2,}", landmark)]
        lower_text = text.lower()
        return any(token in lower_text for token in tokens)

    def _payload_text(self, payload: dict) -> str:
        values = [payload.get("display_name"), payload.get("name")]
        address = payload.get("address") or {}
        if isinstance(address, dict):
            values.extend(address.values())
        return " ".join(self._clean_value(value) for value in values if value)

    def from_nominatim_payload(self, payload: dict, coordinates: Coordinates | None = None) -> ApproximateAddress:
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
            coordinates=coordinates,
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
