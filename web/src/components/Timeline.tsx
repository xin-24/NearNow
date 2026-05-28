import type { ScheduleItem, Plan } from "../api/types";
import { modeLabel, typeLabel } from "../utils/labels";
import styles from "./Timeline.module.css";

interface EditTime {
  start: string;
  end: string;
}

interface Props {
  plan: Plan;
  editingIndex?: number | null;
  editTime?: EditTime;
  onEditTimeChange?: (time: EditTime) => void;
  onStartEdit?: (index: number) => void;
  onSaveEdit?: () => void;
  onCancelEdit?: () => void;
  onRemove?: (index: number) => void;
}

export function Timeline({ plan, editingIndex, editTime, onEditTimeChange, onStartEdit, onSaveEdit, onCancelEdit, onRemove }: Props) {
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
        <TimelineItem
          key={index}
          item={item}
          index={index}
          isEditing={editingIndex === index}
          editTime={editTime}
          onEditTimeChange={onEditTimeChange}
          onStartEdit={() => onStartEdit?.(index)}
          onSaveEdit={onSaveEdit}
          onCancelEdit={onCancelEdit}
          canRemove={item.type === "activity" || item.type === "restaurant"}
          onRemove={() => onRemove?.(index)}
        />
      ))}
    </div>
  );
}

interface TimelineItemProps {
  item: ScheduleItem;
  index: number;
  isEditing: boolean;
  editTime?: EditTime;
  onEditTimeChange?: (time: EditTime) => void;
  onStartEdit?: () => void;
  onSaveEdit?: () => void;
  onCancelEdit?: () => void;
  canRemove: boolean;
  onRemove?: () => void;
}

function TimelineItem({ item, index, isEditing, editTime, onEditTimeChange, onStartEdit, onSaveEdit, onCancelEdit, canRemove, onRemove }: TimelineItemProps) {
  const badge = item.type === "travel" ? modeLabel(item.transport_mode || "") : item.typeLabel || typeLabel(item.type);
  return (
    <article className={styles.item}>
      <div className={styles.dot}>
        <span>{index + 1}</span>
      </div>
      <div className={styles.card}>
        <div className={styles.cardHead}>
          {isEditing && editTime ? (
            <div className={styles.timeEdit}>
              <input
                className={styles.timeInput}
                type="time"
                value={editTime.start}
                onChange={(e) => onEditTimeChange?.({ ...editTime, start: e.target.value })}
              />
              <span>-</span>
              <input
                className={styles.timeInput}
                type="time"
                value={editTime.end}
                onChange={(e) => onEditTimeChange?.({ ...editTime, end: e.target.value })}
              />
              <button className={styles.editBtn} type="button" onClick={onSaveEdit}>保存</button>
              <button className={styles.editBtn} type="button" onClick={onCancelEdit}>取消</button>
            </div>
          ) : (
            <div className={styles.timeDisplay}>
              <span>{item.start_time} - {item.end_time}</span>
              <div className={styles.cardActions}>
                {onStartEdit && (
                  <button className={styles.editBtn} type="button" onClick={onStartEdit}>改时间</button>
                )}
                {canRemove && onRemove && (
                  <button className={styles.removeBtn} type="button" onClick={onRemove}>移除</button>
                )}
              </div>
            </div>
          )}
          <em>{badge}</em>
        </div>
        <h3>{item.name}</h3>
        <p>{item.location}</p>
        <div className={styles.metaRow}>
          <span>{typeLabel(item.type)}</span>
          {item.travel_minutes ? <span>{modeLabel(item.transport_mode || "")} · {item.travel_minutes} 分钟</span> : null}
          {item.route_geometry?.length ? <span>{item.route_geometry.length} 个路线点</span> : null}
        </div>
        <div className={styles.reason}>{item.reason}</div>
      </div>
    </article>
  );
}
