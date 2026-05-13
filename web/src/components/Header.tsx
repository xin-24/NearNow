import type { User } from "../api/types";
import styles from "./Header.module.css";

interface Props {
  user: User | null;
  onLogout: () => void;
  onToggleTheme: () => void;
}

export function Header({ user, onLogout, onToggleTheme }: Props) {
  return (
    <header className={styles.header}>
      <div className={styles.brand}>
        <div className={styles.brandMark} aria-hidden="true">
          <span></span>
        </div>
        <div>
          <h1>
            邻刻计划 <span>NearNow</span>
          </h1>
          <p>Local activity agent</p>
        </div>
      </div>
      <div className={styles.actions}>
        {user && (
          <div className={styles.sessionPill}>
            <span>{user.display_name || user.username}</span>
            <button type="button" onClick={onLogout}>
              退出
            </button>
          </div>
        )}
        <div className={styles.providerPill}>
          <span></span> Real Provider
        </div>
        <button className={styles.iconButton} type="button" aria-label="切换深浅色" onClick={onToggleTheme}>
          <span className={styles.themeIcon}></span>
        </button>
      </div>
    </header>
  );
}
