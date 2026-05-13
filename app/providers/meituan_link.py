from __future__ import annotations

from urllib.parse import quote

from app.agent.context_builder import PlanningContext
from app.domain.models import Restaurant


class MeituanLinkBuilder:
    """Builds public Meituan search handoff links without requiring API credentials."""

    base_url = "https://www.meituan.com/s/"

    def restaurant_search(self, restaurant: Restaurant, context: PlanningContext) -> dict[str, str]:
        query = self._query(
            [
                context.user_context.city,
                context.user_context.district,
                restaurant.name,
                restaurant.location,
            ]
        )
        return {
            "provider": "meituan",
            "label": "去美团查看/下单",
            "url": f"{self.base_url}{quote(query)}",
            "query": query,
            "note": "这是美团搜索跳转链接，需要用户自行确认是否为同一家店并完成下单或订座。",
        }

    def _query(self, parts: list[str | None]) -> str:
        result: list[str] = []
        for part in parts:
            for token in str(part or "").replace("/", " ").split():
                if token and token not in result:
                    result.append(token)
        return " ".join(result)
