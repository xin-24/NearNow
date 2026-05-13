import styles from "./ProgressRing.module.css";

interface Props {
  percent: number;
}

export function ProgressRing({ percent }: Props) {
  const circumference = 326.7;
  const offset = circumference - (percent / 100) * circumference;

  return (
    <div className={styles.ring}>
      <svg viewBox="0 0 120 120" aria-hidden="true">
        <circle cx="60" cy="60" r="52" className={styles.track}></circle>
        <circle
          cx="60"
          cy="60"
          r="52"
          className={styles.arc}
          style={{ strokeDasharray: circumference, strokeDashoffset: offset }}
        ></circle>
      </svg>
      <div>{percent}%</div>
    </div>
  );
}
