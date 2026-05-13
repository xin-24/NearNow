import type { ScheduleItem, Plan } from "../api/types";
import { modeLabel, typeLabel } from "../utils/labels";
import styles from "./Timeline.module.css";

interface Props {
  plan: Plan;
}

export function Timeline({ plan }: Props) {
  if (!plan.schedule.length) {
    const reasons = plan.risk_notes.length
      ? plan.risk_notes
      : [plan.final_message || "当前条件下没有可执行时间轴。"];
    return (
      <div className={styles.empty}>
        <strong>暂未生成可执行时间轴</strong>
        <p>{plan.final_message || plan.summary || "需要补充或放宽条件后继续规划。"}</p>
        <div className={styles.emptyChips}>
          {reasons.map((r, i) => (
            <span key={i} className={styles.emptyChip}>{r}</span>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className={styles.timeline}>
      {plan.schedule.map((item, index) => (
        <TimelineItem key={index} item={item} index={index} />
      ))}
    </div>
  );
}

function TimelineItem({ item, index }: { item: ScheduleItem; index: number }) {
  const badge = item.type === "travel" ? modeLabel(item.transport_mode || "") : item.typeLabel || typeLabel(item.type);
  return (
    <article className={styles.item}>
      <div className={styles.dot}>
        <span>{index + 1}</span>
      </div>
      <div className={styles.card}>
        <div className={styles.cardHead}>
          <span>{item.start_time} - {item.end_time}</span>
          <em>{badge}</em>
        </div>
        <h3>{item.name}</h3>
        <p>{item.location}</p>
        <div className={styles.reason}>{item.reason}</div>
      </div>
    </article>
  );
}
