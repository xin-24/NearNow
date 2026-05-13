import { useState } from "react";
import type { LocationStatus } from "../hooks/useLocation";
import { ExampleGrid } from "../components/ExampleGrid";
import styles from "./InputView.module.css";

interface Props {
  defaultGoal: string;
  defaultCompanions: string;
  origin: string;
  locationStatus: LocationStatus;
  locating: boolean;
  onOriginChange: (value: string) => void;
  onLocate: () => void;
  onPlan: (goal: string, companions: string) => void;
}

export function InputView({
  defaultGoal,
  defaultCompanions,
  origin,
  locationStatus,
  locating,
  onOriginChange,
  onLocate,
  onPlan,
}: Props) {
  const [goal, setGoal] = useState(defaultGoal);
  const [companions, setCompanions] = useState(defaultCompanions);

  return (
    <section className={styles.view}>
      <div className={styles.copy}>
        <p className={styles.eyebrow}>Planning · Booking · Route</p>
        <h2>告诉我这几个小时想怎么过</h2>
        <p>我会把参与者、地点、交通、餐厅和可执行动作整理成一条计划。</p>
      </div>

      <section className={styles.composer}>
        <label className={styles.label}>活动目标</label>
        <textarea
          className={styles.textarea}
          rows={5}
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
        />
        <label className={styles.label}>通知同行人</label>
        <textarea
          className={styles.compactTextarea}
          rows={3}
          value={companions}
          onChange={(e) => setCompanions(e.target.value)}
          placeholder={"每行一个：小张 朋友 13800000000\nLily 闺蜜 lily@example.com"}
        />
        <p className={styles.companionHelp}>确认计划后，这些人会作为待发送通知对象保存。</p>
        <div className={styles.footer}>
          <div className={styles.locationStrip}>
            <label className={styles.locationField}>
              出发位置
              <span className={styles.locationShell}>
                <input
                  value={origin}
                  onChange={(e) => onOriginChange(e.target.value)}
                  placeholder="城市 + 区/县 + 商圈/地标，如 北京 朝阳区 望京 SOHO"
                />
                <button className={styles.locateBtn} type="button" onClick={onLocate} disabled={locating}>
                  {locating ? "定位中..." : "定位"}
                </button>
              </span>
            </label>
          </div>
          <button className={styles.planBtn} type="button" onClick={() => onPlan(goal, companions)}>
            <span>生成方案</span>
          </button>
        </div>
        <p className={`${styles.locationStatus} ${styles[locationStatus.state]}`}>{locationStatus.message}</p>
      </section>

      <ExampleGrid onSelect={(text) => setGoal(text)} />
    </section>
  );
}
