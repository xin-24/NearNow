from __future__ import annotations

import json

from app.agent.response_generator import ResponseGenerator
from app.domain.models import Plan
from app.providers.longcat_client import LongCatAPIError, LongCatClient


class LongCatResponseGenerator:
    """Plan summary generation that surfaces API failures to the caller."""

    def __init__(self, fallback: ResponseGenerator, client: LongCatClient) -> None:
        self.fallback = fallback
        self.client = client

    def summarize_plan(self, plan: Plan) -> str:
        fallback_summary = self.fallback.summarize_plan(plan)
        if not self.client.is_configured:
            return fallback_summary

        try:
            content = self.client.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是 NearNow 的行程确认助手。"
                            "请用简洁、可执行的中文改写计划摘要，保留所有时间、地点、交通和待确认动作。"
                            "不要向用户提及 provider、API、真实地图 POI、osm_overpass、amap 等工程字段。"
                            "如果地点或餐厅来自地图候选，只能用普通推荐口吻说明它适合当前偏好和动线，"
                            "不要声称已经确认营业、无需等位、已订座、有余位、评分或人均；这些状态必须提示出发前复查。"
                            "provider 为 mock 时也不要强调数据来源，只说明推荐理由。"
                            "如果 reserve_restaurant 动作 payload 包含 handoff_provider 或 handoff_url，"
                            "只能说已提供第三方跳转链接，需要用户在外部页面自行确认并完成下单或订座，不能说已经自动订座。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "fallback_summary": fallback_summary,
                                "plan": plan.to_dict(),
                                "style": "自然、清楚、可直接发给同行者，避免夸张营销语。",
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                max_tokens=1000,
                temperature=0.3,
            )

            if not content:
                return fallback_summary
            return content
        except LongCatAPIError:
            return fallback_summary
