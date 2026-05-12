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
            raise LongCatAPIError("LONGCAT_API_KEY is not configured")

        content = self.client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "你是 NearNow 的行程确认助手。"
                        "请用简洁、可执行的中文改写计划摘要，保留所有时间、地点、交通和待确认动作。"
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
            raise LongCatAPIError("LongCat response content was empty")
        return content
