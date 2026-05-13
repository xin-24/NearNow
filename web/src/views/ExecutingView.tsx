import { useEffect, useRef, useState } from "react";
import { ProgressRing } from "../components/ProgressRing";
import { StepList } from "../components/StepList";
import { actionLabel } from "../utils/labels";
import type { PendingAction } from "../api/types";
import styles from "./ProcessView.module.css";

interface Props {
  actions: PendingAction[];
}

export function ExecutingView({ actions }: Props) {
  const [percent, setPercent] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const steps = actions.map((a) => actionLabel(a.type, a.target));

  useEffect(() => {
    let progress = 0;
    timerRef.current = setInterval(() => {
      progress = Math.min(100, progress + 25);
      setPercent(progress);
      if (progress >= 100 && timerRef.current) clearInterval(timerRef.current);
    }, 1000 / 4);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, []);

  return (
    <section className={styles.view}>
      <ProgressRing percent={percent} />
      <h2>Agent 执行中</h2>
      <StepList steps={steps} progress={percent} />
    </section>
  );
}
