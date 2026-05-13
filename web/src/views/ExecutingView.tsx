import { useEffect, useState } from "react";
import { StepList } from "../components/StepList";
import { actionLabel } from "../utils/labels";
import type { PendingAction } from "../api/types";
import styles from "./ProcessView.module.css";

interface Props {
  actions: PendingAction[];
  onCancel: () => void;
}

export function ExecutingView({ actions, onCancel }: Props) {
  const [activeStep, setActiveStep] = useState(0);
  const steps = actions.map((a) => actionLabel(a.type, a.target));

  useEffect(() => {
    const timer = setInterval(() => {
      setActiveStep((prev) => Math.min(prev + 1, steps.length - 1));
    }, 1500);
    return () => clearInterval(timer);
  }, [steps.length]);

  return (
    <section className={styles.view}>
      <div className={styles.spinner}>
        <div className={styles.spinnerRing}></div>
      </div>
      <h2>Agent 执行中</h2>
      <p className={styles.hint}>正在执行预约和通知，请稍候...</p>
      <StepList steps={steps} activeIndex={activeStep} />
      <button className={styles.cancelBtn} type="button" onClick={onCancel}>
        取消
      </button>
    </section>
  );
}
