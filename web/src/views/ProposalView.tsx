import type { Plan } from "../api/types";
import { Timeline } from "../components/Timeline";
import { ChipList } from "../components/ChipList";
import { RouteSelector } from "../components/RouteSelector";
import { modeLabel, actionTypeLabel } from "../utils/labels";
import { selectedRoute, inferPartySize, selectRoute, preparePlanForRouteEditing } from "../utils/route";
import styles from "./ProposalView.module.css";
import { useState } from "react";

interface Props {
  plan: Plan;
  onEdit: () => void;
  onConfirm: () => void;
  onRouteChange: (updatedPlan: Plan) => void;
}

export function ProposalView({ plan, onEdit, onConfirm, onRouteChange }: Props) {
  const [, forceUpdate] = useState(0);
  preparePlanForRouteEditing(plan);
  const route = selectedRoute(plan);

  const handleRouteSelect = (mode: string) => {
    selectRoute(plan, mode);
    onRouteChange(plan);
    forceUpdate((n) => n + 1);
  };

  return (
    <section className={styles.view}>
      <div className={styles.head}>
        <div>
          <p className={styles.eyebrow}>Generated plan</p>
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

      <section className={styles.planBoard}>
        <div className={styles.timelineColumn}>
          <h3>时间轴</h3>
          <Timeline plan={plan} />
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
            <ChipList items={plan.pending_actions.map((a) => `${actionTypeLabel(a.type)} · ${a.target}`)} />
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
