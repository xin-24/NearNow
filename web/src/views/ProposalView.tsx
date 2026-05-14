import { useState, useCallback } from "react";
import type { Plan, HandoffLink } from "../api/types";
import { Timeline } from "../components/Timeline";
import { ChipList } from "../components/ChipList";
import { RouteSelector } from "../components/RouteSelector";
import { RouteMap } from "../components/RouteMap";
import { modeLabel, actionTypeLabel } from "../utils/labels";
import { selectedRoute, inferPartySize, preparePlanForRouteEditing, selectRoute } from "../utils/route";
import styles from "./ProposalView.module.css";

interface Props {
  plan: Plan;
  onEdit: () => void;
  onConfirm: () => void;
  onRouteChange: (updatedPlan: Plan) => void;
  onPlanUpdate: (updatedPlan: Plan) => void;
}

export function ProposalView({ plan, onEdit, onConfirm, onRouteChange, onPlanUpdate }: Props) {
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [editTime, setEditTime] = useState({ start: "", end: "" });

  preparePlanForRouteEditing(plan);
  const route = selectedRoute(plan);

  const handleRouteSelect = useCallback(
    (mode: string) => {
      const updated = structuredClone(plan);
      selectRoute(updated, mode);
      onRouteChange(updated);
    },
    [plan, onRouteChange],
  );

  const handleStartTimeEdit = useCallback(
    (index: number) => {
      setEditingIndex(index);
      setEditTime({ start: plan.schedule[index].start_time, end: plan.schedule[index].end_time });
    },
    [plan],
  );

  const handleStartTimeSave = useCallback(() => {
    if (editingIndex === null) return;
    const updated = structuredClone(plan);
    const item = updated.schedule[editingIndex];
    const oldStart = item.start_time;
    item.start_time = editTime.start;
    item.end_time = editTime.end;

    const delta = minutesDiff(editTime.start, oldStart);
    if (delta !== 0) {
      updated.schedule.slice(editingIndex + 1).forEach((s) => {
        s.start_time = addMinutes(s.start_time, delta);
        s.end_time = addMinutes(s.end_time, delta);
      });
    }

    setEditingIndex(null);
    onPlanUpdate(updated);
  }, [plan, editingIndex, editTime, onPlanUpdate]);

  const handleRemoveItem = useCallback(
    (index: number) => {
      const updated = structuredClone(plan);
      const removed = updated.schedule[index];
      updated.schedule.splice(index, 1);
      if (removed.type === "activity" || removed.type === "restaurant") {
        updated.pending_actions = updated.pending_actions.filter((a) => {
          if (removed.type === "activity" && a.type === "book_activity") return false;
          if (removed.type === "restaurant" && a.type === "reserve_restaurant") return false;
          return true;
        });
      }
      onPlanUpdate(updated);
    },
    [plan, onPlanUpdate],
  );

  const executableActions = plan.pending_actions.map((action) => {
    const handoffUrl = typeof action.payload.handoff_url === "string" ? action.payload.handoff_url : "";
    const handoffLabel =
      typeof action.payload.handoff_label === "string" ? action.payload.handoff_label : "去预订";
    const handoffLinks = Array.isArray(action.payload.handoff_links)
      ? (action.payload.handoff_links as HandoffLink[])
      : [];
    return (
      <div key={action.action_id} className={styles.actionItem}>
        <span>{`${actionTypeLabel(action.type)} · ${action.target}`}</span>
        {handoffLinks.length > 0 ? (
          <div className={styles.linkGroup}>
            {handoffLinks.map((link) => (
              <a key={link.platform} className={styles.linkBtn} href={link.url} target="_blank" rel="noreferrer">
                {link.label}
              </a>
            ))}
          </div>
        ) : handoffUrl ? (
          <a href={handoffUrl} target="_blank" rel="noreferrer">
            {handoffLabel}
          </a>
        ) : null}
      </div>
    );
  });

  return (
    <section className={styles.view}>
      <div className={styles.head}>
        <div>
          <p className={styles.eyebrow}>为你定制的计划</p>
          <h2>{plan.title}</h2>
          <p>{plan.summary}</p>
        </div>
        <button className={styles.ghostBtn} type="button" onClick={onEdit}>
          重新输入
        </button>
      </div>

      <section className={styles.insightGrid}>
        <article>
          <span>同行规模</span>
          <strong>{inferPartySize(plan)}</strong>
        </article>
        <article>
          <span>推荐交通</span>
          <strong>{route ? modeLabel(route.mode) : "-"}</strong>
        </article>
        <article>
          <span>待执行动作</span>
          <strong>{plan.pending_actions.length}</strong>
        </article>
        <article>
          <span>完成时间</span>
          <strong>{plan.schedule.length ? plan.schedule[plan.schedule.length - 1].end_time : "-"}</strong>
        </article>
      </section>

      <RouteMap plan={plan} />

      <section className={styles.planBoard}>
        <div className={styles.timelineColumn}>
          <h3>时间轴</h3>
          <Timeline
            plan={plan}
            editingIndex={editingIndex}
            editTime={editTime}
            onEditTimeChange={setEditTime}
            onStartEdit={handleStartTimeEdit}
            onSaveEdit={handleStartTimeSave}
            onCancelEdit={() => setEditingIndex(null)}
            onRemove={handleRemoveItem}
          />
        </div>
        <aside className={styles.sideColumn}>
          <section className={styles.sideCard}>
            <h3>参与者约束</h3>
            <ChipList items={plan.participant_summary} />
          </section>
          <section className={styles.sideCard}>
            <h3>交通方式比较</h3>
            <RouteSelector routes={plan.route_options} onSelect={handleRouteSelect} />
          </section>
          <section className={styles.sideCard}>
            <h3>确认后执行</h3>
            <div className={styles.actionList}>{executableActions}</div>
          </section>
          {plan.risk_notes.length > 0 && (
            <section className={styles.sideCard}>
              <h3>风险提示</h3>
              <ChipList items={plan.risk_notes} variant="warning" />
            </section>
          )}
        </aside>
      </section>

      <div className={styles.dock}>
        <p>确认后才会执行预约、订座和通知。</p>
        <button className={styles.primaryBtn} type="button" onClick={onConfirm}>
          一键执行
        </button>
      </div>
    </section>
  );
}

function addMinutes(timeText: string, minutes: number): string {
  const [hour, minute] = String(timeText || "00:00").split(":").map((v) => Number.parseInt(v, 10));
  const date = new Date(2000, 0, 1, Number.isFinite(hour) ? hour : 0, Number.isFinite(minute) ? minute : 0);
  date.setMinutes(date.getMinutes() + minutes);
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function minutesDiff(a: string, b: string): number {
  const [ah, am] = a.split(":").map(Number);
  const [bh, bm] = b.split(":").map(Number);
  return (ah * 60 + am) - (bh * 60 + bm);
}
