import { useEffect, useState } from "react";
import { StepList } from "../components/StepList";
import styles from "./ProcessView.module.css";

const analyzingSteps = [
  "提取时间与参与者画像",
  "解析距离偏好与交通方式",
  "匹配附近活动与餐饮资源",
  "生成可执行活动方案",
];

interface Props {
  onCancel: () => void;
}

export function AnalyzingView({ onCancel }: Props) {
  const [activeStep, setActiveStep] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setActiveStep((prev) => Math.min(prev + 1, analyzingSteps.length - 1));
    }, 2000);
    return () => clearInterval(timer);
  }, []);

  return (
    <section className={styles.view}>
      <div className={styles.spinner}>
        <div className={styles.spinnerRing}></div>
      </div>
      <h2>Agent 正在规划</h2>
      <p className={styles.hint}>正在分析你的需求并匹配附近资源，通常需要 5-10 秒...</p>
      <StepList steps={analyzingSteps} activeIndex={activeStep} />
      <button className={styles.cancelBtn} type="button" onClick={onCancel}>
        取消
      </button>
    </section>
  );
}
