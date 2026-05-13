import styles from "./StepList.module.css";

interface Props {
  steps: string[];
  activeIndex: number;
}

export function StepList({ steps, activeIndex }: Props) {
  return (
    <div className={styles.list}>
      {steps.map((step, index) => {
        const done = index < activeIndex;
        const active = index === activeIndex;
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
