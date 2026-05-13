import styles from "./ExampleGrid.module.css";

interface Example {
  label: string;
  description: string;
  text: string;
}

const examples: Example[] = [
  { label: "浪漫约会", description: "恋人 · 仪式感 · 不开车", text: "晚上和女朋友约会，想先吃顿日料，然后看场浪漫的电影，不想开车。" },
  { label: "朋友小聚", description: "咖啡 · 桌游 · 附近", text: "今天下午，我和同学想在附近喝杯手冲咖啡，然后找个地方玩一两个小时桌游。" },
  { label: "宠物同行", description: "可携宠 · 公园 · 餐厅", text: "下午带狗出去玩，顺便找个能带宠物的地方吃饭。" },
  { label: "陪伴长辈", description: "少走路 · 安静 · 清淡", text: "陪爸妈附近走走，别太累，晚饭清淡一点。" },
];

interface Props {
  onSelect: (text: string) => void;
}

export function ExampleGrid({ onSelect }: Props) {
  return (
    <section className={styles.grid} aria-label="示例目标">
      {examples.map((example) => (
        <button key={example.label} type="button" onClick={() => onSelect(example.text)}>
          <span>{example.label}</span>
          <strong>{example.description}</strong>
        </button>
      ))}
    </section>
  );
}
