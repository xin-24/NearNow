from __future__ import annotations

import json
import sys

from app.agent.orchestrator import LocalPlannerAgent


def main() -> int:
    message = " ".join(sys.argv[1:]).strip()
    if not message:
        message = input("请输入活动目标：").strip()

    agent = LocalPlannerAgent()
    response = agent.plan(
        {
            "message": message,
            "mode": "mock",
            "user_context": {
                "home_location": "望京 SOHO",
                "city": "北京",
                "coordinates": {"lat": 39.9957, "lng": 116.4813},
            },
        }
    )
    print(json.dumps(response, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

