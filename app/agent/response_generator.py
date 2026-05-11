from __future__ import annotations

from app.domain.models import Plan


class ResponseGenerator:
    def summarize_plan(self, plan: Plan) -> str:
        if plan.final_message:
            return plan.final_message
        lines = [plan.summary, ""]
        for item in plan.schedule:
            transport = f"（{item.transport_mode}，约 {item.travel_minutes} 分钟）" if item.type == "travel" else ""
            lines.append(f"{item.start_time}-{item.end_time} {item.name}{transport}")
        if plan.participant_summary:
            lines.append("")
            lines.extend(plan.participant_summary)
        if plan.pending_actions:
            lines.append("")
            lines.append("确认后我会执行这些动作：")
            for action in plan.pending_actions:
                lines.append(f"- {action.type}: {action.target}")
        return "\n".join(lines)

