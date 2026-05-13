import { useEffect, useRef, useState } from "react";
import { ProgressRing } from "../components/ProgressRing";
import { StepList } from "../components/StepList";
import styles from "./ProcessView.module.css";

const analyzingSteps = [
  "提取时间与参与者画像",
  "解析距离偏好与交通方式",
  "匹配附近活动与餐饮资源",
  "生成可执行活动方案",
];

export function AnalyzingView() {
  const [percent, setPercent] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval>>();

  useEffect(() => {
    let progress = 0;
    timerRef.current = setInterval(() => {
      progress = Math.min(100, progress + 25);
      setPercent(progress);
      if (progress >= 100) clearInterval(timerRef.current);
    }, 900 / 4);
    return () => clearInterval(timerRef.current);
  }, []);

  return (
    <section className={styles.view}>
      <ProgressRing percent={percent} />
      <h2>Agent 正在规划</h2>
      <StepList steps={analyzingSteps} progress={percent} />
    </section>
  );
}
