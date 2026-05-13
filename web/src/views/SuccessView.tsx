import type { ExecutionResponse } from "../api/types";
import { Receipt } from "../components/Receipt";
import styles from "./SuccessView.module.css";

interface Props {
  result: ExecutionResponse;
  onNewPlan: () => void;
}

export function SuccessView({ result, onNewPlan }: Props) {
  return (
    <section className={styles.view}>
      <div className={styles.mark}>
        <span></span>
      </div>
      <h2>一切安排妥当</h2>
      <p>{result.final_message}</p>
      <Receipt result={result} />
      <button className={styles.ghostBtn} type="button" onClick={onNewPlan}>
        新建另一个活动
      </button>
    </section>
  );
}
