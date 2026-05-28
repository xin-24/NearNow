import { useState, type FormEvent } from "react";
import styles from "./LoginView.module.css";

interface Props {
  onLogin: (username: string, password: string, displayName: string) => Promise<void>;
}

export function LoginView({ onLogin }: Props) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");

    const trimmedUsername = username.trim();
    const trimmedPassword = password.trim();
    if (!trimmedUsername) {
      setError("请输入账号");
      return;
    }
    if (!trimmedPassword) {
      setError("请输入密码");
      return;
    }
    if (trimmedPassword.length < 6) {
      setError("密码至少需要 6 位");
      return;
    }

    setSubmitting(true);
    try {
      await onLogin(trimmedUsername, trimmedPassword, displayName.trim());
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section className={styles.view}>
      <div className={styles.copy}>
        <p className={styles.eyebrow}>NearNow Account</p>
        <h2>先确认你的规划身份</h2>
        <p>后续会把出发位置、计划记录和需要通知的同行人保存到你的账号下。</p>
      </div>
      <form className={styles.card} onSubmit={handleSubmit}>
        <label className={styles.field}>
          账号
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            placeholder="例如 xin"
          />
        </label>
        <label className={styles.field}>
          密码
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            placeholder="至少 6 位"
          />
        </label>
        <label className={styles.field}>
          显示名称
          <input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            autoComplete="name"
            placeholder="首次登录时用于创建账号"
          />
        </label>
        {error && <p className={styles.error}>{error}</p>}
        <button className={styles.primaryBtn} type="submit" disabled={submitting}>
          进入 NearNow
        </button>
      </form>
    </section>
  );
}
