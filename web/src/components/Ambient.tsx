import styles from "./Ambient.module.css";

export function Ambient() {
  return (
    <div className={styles.ambient} aria-hidden="true">
      <div className={`${styles.mesh} ${styles.meshA}`}></div>
      <div className={`${styles.mesh} ${styles.meshB}`}></div>
      <div className={styles.grain}></div>
    </div>
  );
}
