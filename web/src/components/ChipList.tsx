import styles from "./ChipList.module.css";

interface Props {
  items: string[];
  variant?: "default" | "warning";
}

export function ChipList({ items, variant = "default" }: Props) {
  return (
    <div className={`${styles.chips} ${variant === "warning" ? styles.warning : ""}`}>
      {items.map((item, index) => (
        <span key={index} className={styles.chip}>
          {item}
        </span>
      ))}
    </div>
  );
}
