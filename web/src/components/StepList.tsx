import styles from "./StepList.module.css";

interface Props {
  steps: string[];
  progress: number;
}

export function StepList({ steps, progress }: Props) {
  return (
    <div className={styles.list}>
      {steps.map((step, index) => {
        const threshold = ((index + 1) / steps.length) * 100;
        const done = progress >= threshold;
        const active = progress > (index / steps.length) * 100 && progress < threshold;
        return (
          <div
            key={index}
            className={`${styles.step} ${done ? styles.done : ""} ${active ? styles.active : ""}`}
          >
            <span></span>
            <p>{step}</p>
          </div>
        );
      })}
    </div>
  );
}
