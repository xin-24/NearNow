import type { ExecutionResponse } from "../api/types";
import { actionTypeLabel } from "../utils/labels";
import styles from "./Receipt.module.css";

interface Props {
  result: ExecutionResponse;
}

export function Receipt({ result }: Props) {
  return (
    <section className={styles.receipt}>
      <div className={styles.top}>
        <span>NearNow Itinerary</span>
        <strong>{result.execution_status === "completed" ? "执行成功" : "部分完成"}</strong>
      </div>
      <div className={styles.items}>
        {result.results.map((item, index) => {
          const no = item.confirmation_no || item.message_id || item.booking_id || "已记录";
          return (
            <article key={index} className={styles.item}>
              <div>
                <span>{actionTypeLabel(item.type)}</span>
                <strong>{item.status}</strong>
              </div>
              <code>{no}</code>
            </article>
          );
        })}
      </div>
    </section>
  );
}
