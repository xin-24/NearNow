import type { RouteOption } from "../api/types";
import { modeLabel } from "../utils/labels";
import styles from "./RouteSelector.module.css";

interface Props {
  routes: RouteOption[];
  onSelect: (mode: string) => void;
}

export function RouteSelector({ routes, onSelect }: Props) {
  return (
    <div className={styles.list}>
      {routes.map((route) => (
        <button
          key={route.mode}
          className={`${styles.item} ${route.selected ? styles.selected : ""}`}
          type="button"
          aria-pressed={route.selected ? "true" : "false"}
          onClick={() => onSelect(route.mode)}
        >
          <div>
            <strong>{modeLabel(route.mode)}</strong>
            <span>{route.duration_minutes} 分钟 &middot; {route.distance_km} km</span>
          </div>
          <em>{route.selected ? "已选" : `${route.estimated_cost} 元`}</em>
        </button>
      ))}
    </div>
  );
}
