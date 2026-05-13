import type { ExecutionResponse, HandoffLink } from "../api/types";
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
          const no = item.confirmation_no || item.message_id || item.booking_id || item.message || "已记录";
          const links: HandoffLink[] = Array.isArray(item.handoff_links) ? item.handoff_links : [];
          return (
            <article key={index} className={styles.item}>
              <div>
                <span>{actionTypeLabel(item.type)}</span>
                <strong>{item.status === "handoff_required" ? "需手动完成" : item.status}</strong>
              </div>
              {links.length > 0 ? (
                <div className={styles.linkGroup}>
                  {links.map((link) => (
                    <a key={link.platform} className={styles.linkBtn} href={link.url} target="_blank" rel="noreferrer">
                      {link.label}
                    </a>
                  ))}
                </div>
              ) : item.handoff_url ? (
                <a href={item.handoff_url} target="_blank" rel="noreferrer">
                  {item.handoff_label || "去预订"}
                </a>
              ) : (
                <code>{no}</code>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
