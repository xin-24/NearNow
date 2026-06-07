import { useState, useCallback, useEffect, useMemo } from "react";
import type { Plan, HandoffLink, PlanAlternative } from "../api/types";
import { Timeline } from "../components/Timeline";
import { ChipList } from "../components/ChipList";
import { RouteSelector } from "../components/RouteSelector";
import { RouteMap } from "../components/RouteMap";
import { modeLabel, actionTypeLabel } from "../utils/labels";
import {
  selectedRoute,
  inferPartySize,
  preparePlanForRouteEditing,
  selectRoute,
  addMinutes,
  syncPendingActionTimes,
  removePendingActionForScheduleItem,
} from "../utils/route";
import styles from "./ProposalView.module.css";

interface Props {
  plan: Plan;
  onEdit: () => void;
  onConfirm: (plan: Plan) => void;
  onRouteChange: (updatedPlan: Plan) => void;
  onPlanUpdate: (updatedPlan: Plan) => void;
}

export function ProposalView({ plan, onEdit, onConfirm, onRouteChange, onPlanUpdate }: Props) {
  const options = useMemo(() => buildPlanOptions(plan), [plan]);
  const [selectedOption, setSelectedOption] = useState(0);
  const [activePlan, setActivePlan] = useState<Plan>(() => editablePlan(options[0].plan));
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [editTime, setEditTime] = useState({ start: "", end: "" });

  useEffect(() => {
    setSelectedOption(0);
    setActivePlan(editablePlan(buildPlanOptions(plan)[0].plan));
    setEditingIndex(null);
  }, [plan.plan_id]);

  const route = selectedRoute(activePlan);

  const handleOptionSelect = useCallback(
    (index: number) => {
      const option = options[index];
      if (!option) return;
      setSelectedOption(index);
      setEditingIndex(null);
      setActivePlan(editablePlan(option.plan));
    },
    [options],
  );

  const handleRouteSelect = useCallback(
    (mode: string) => {
      const updated = structuredClone(activePlan);
      selectRoute(updated, mode);
      setActivePlan(updated);
      if (selectedOption === 0) {
        onRouteChange(updated);
      }
    },
    [activePlan, selectedOption, onRouteChange],
  );

  const handleStartTimeEdit = useCallback(
    (index: number) => {
      setEditingIndex(index);
      setEditTime({ start: activePlan.schedule[index].start_time, end: activePlan.schedule[index].end_time });
    },
    [activePlan],
  );

  const handleStartTimeSave = useCallback(() => {
    if (editingIndex === null) return;
    const updated = structuredClone(activePlan);
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
    syncPendingActionTimes(updated);

    setEditingIndex(null);
    setActivePlan(updated);
    if (selectedOption === 0) {
      onPlanUpdate(updated);
    }
  }, [activePlan, editingIndex, editTime, selectedOption, onPlanUpdate]);

  const handleRemoveItem = useCallback(
    (index: number) => {
      const updated = structuredClone(activePlan);
      const removed = updated.schedule[index];
      removePendingActionForScheduleItem(updated, removed, updated.schedule);
      updated.schedule.splice(index, 1);
      syncPendingActionTimes(updated);
      setActivePlan(updated);
      if (selectedOption === 0) {
        onPlanUpdate(updated);
      }
    },
    [activePlan, selectedOption, onPlanUpdate],
  );

  const executableActions = activePlan.pending_actions.map((action) => {
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
          <h2>{activePlan.title}</h2>
          <p>{activePlan.summary}</p>
        </div>
        <button className={styles.ghostBtn} type="button" onClick={onEdit}>
          重新输入
        </button>
      </div>

      <section className={styles.insightGrid}>
        <article>
          <span>同行规模</span>
          <strong>{inferPartySize(activePlan)}</strong>
        </article>
        <article>
          <span>推荐交通</span>
          <strong>{route ? modeLabel(route.mode) : "-"}</strong>
        </article>
        <article>
          <span>待执行动作</span>
          <strong>{activePlan.pending_actions.length}</strong>
        </article>
        <article>
          <span>完成时间</span>
          <strong>{activePlan.schedule.length ? activePlan.schedule[activePlan.schedule.length - 1].end_time : "-"}</strong>
        </article>
      </section>

      <section className={styles.optionGrid} aria-label="方案权重选择">
        {options.map((option, index) => (
          <button
            key={option.key}
            type="button"
            className={`${styles.optionCard} ${index === selectedOption ? styles.optionActive : ""}`}
            onClick={() => handleOptionSelect(index)}
          >
            <span>{option.label}</span>
            <strong>{option.title}</strong>
            <p>{option.tradeoff}</p>
          </button>
        ))}
      </section>

      <RouteMap plan={activePlan} />

      <section className={styles.planBoard}>
        <div className={styles.timelineColumn}>
          <h3>时间轴</h3>
          <Timeline
            plan={activePlan}
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
            <ChipList items={activePlan.participant_summary} />
          </section>
          <section className={styles.sideCard}>
            <h3>交通方式比较</h3>
            <RouteSelector routes={activePlan.route_options} onSelect={handleRouteSelect} />
          </section>
          <section className={styles.sideCard}>
            <h3>确认后执行</h3>
            <div className={styles.actionList}>{executableActions}</div>
          </section>
          {activePlan.risk_notes.length > 0 && (
            <section className={styles.sideCard}>
              <h3>风险提示</h3>
              <ChipList items={activePlan.risk_notes} variant="warning" />
            </section>
          )}
        </aside>
      </section>

      <div className={styles.dock}>
        <p>确认后才会执行预约、订座和通知。</p>
        <button className={styles.primaryBtn} type="button" onClick={() => onConfirm(activePlan)}>
          一键执行
        </button>
      </div>
    </section>
  );
}

function buildPlanOptions(plan: Plan) {
  const alternatives = (plan.alternatives || []).filter((item): item is PlanAlternative & { plan: Plan } => Boolean(item.plan));
  return [
    {
      key: "balanced",
      label: "综合推荐",
      title: plan.title,
      tradeoff: "画像、距离、交通和餐饮体验均衡。",
      plan,
    },
    ...alternatives.map((item) => ({
      key: item.strategy,
      label: item.label,
      title: item.title,
      tradeoff: item.tradeoff || item.reason,
      plan: item.plan,
    })),
  ];
}

function editablePlan(plan: Plan): Plan {
  const cloned = structuredClone(plan);
  preparePlanForRouteEditing(cloned);
  syncPendingActionTimes(cloned);
  return cloned;
}

function minutesDiff(a: string, b: string): number {
  const [ah, am] = a.split(":").map(Number);
  const [bh, bm] = b.split(":").map(Number);
  return (ah * 60 + am) - (bh * 60 + bm);
}
