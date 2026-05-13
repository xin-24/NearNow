import styles from "./ErrorView.module.css";

interface Props {
  message: string;
  onBack: () => void;
}

export function ErrorView({ message, onBack }: Props) {
  return (
    <section className={styles.view}>
      <div className={styles.card}>
        <h2>需要调整一下</h2>
        <p>{message}</p>
        <button className={styles.primaryBtn} type="button" onClick={onBack}>
          返回修改
        </button>
      </div>
    </section>
  );
}
