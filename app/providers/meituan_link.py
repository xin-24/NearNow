from __future__ import annotations

from urllib.parse import quote

from app.agent.context_builder import PlanningContext
from app.domain.models import Restaurant


class HandoffLinkBuilder:
    """Builds multi-platform handoff links for restaurants and activities."""

    MEITUAN_WEB = "https://www.meituan.com/s/"
    MEITUAN_APP = "imeituan://www.meituan.com/s/"
    DIANPING_APP = "dianping://searchshop/"

    def restaurant_search(self, restaurant: Restaurant, context: PlanningContext) -> dict:
        query = self._query([
            context.user_context.city,
            context.user_context.district,
            restaurant.name,
            restaurant.location,
        ])
        encoded = quote(query)
        return {
            "provider": "multi",
            "label": "去预订",
            "url": f"{self.MEITUAN_WEB}{encoded}",
            "links": [
                {"platform": "meituan_app", "label": "美团 App", "url": f"{self.MEITUAN_APP}{encoded}"},
                {"platform": "dianping_app", "label": "大众点评", "url": f"{self.DIANPING_APP}{encoded}"},
                {"platform": "meituan_web", "label": "美团网页", "url": f"{self.MEITUAN_WEB}{encoded}"},
            ],
            "query": query,
            "note": "将跳转到对应平台搜索页，请确认是否为同一家店后完成预订。",
        }

    def activity_search(self, activity_name: str, context: PlanningContext) -> dict:
        query = self._query([
            context.user_context.city,
            context.user_context.district,
            activity_name,
        ])
        encoded = quote(query)
        return {
            "provider": "multi",
            "label": "去查看",
            "url": f"{self.MEITUAN_WEB}{encoded}",
            "links": [
                {"platform": "meituan_app", "label": "美团 App", "url": f"{self.MEITUAN_APP}{encoded}"},
                {"platform": "dianping_app", "label": "大众点评", "url": f"{self.DIANPING_APP}{encoded}"},
                {"platform": "meituan_web", "label": "美团网页", "url": f"{self.MEITUAN_WEB}{encoded}"},
            ],
            "query": query,
            "note": "将跳转到对应平台搜索页，请确认后完成预订。",
        }

    def _query(self, parts: list[str | None]) -> str:
        result: list[str] = []
        for part in parts:
            for token in str(part or "").replace("/", " ").split():
                if token and token not in result:
                    result.append(token)
        return " ".join(result)
