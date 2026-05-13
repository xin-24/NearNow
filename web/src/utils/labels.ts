export function modeLabel(mode: string): string {
  const map: Record<string, string> = {
    walking: "步行",
    driving: "驾车",
    public_transit: "公交/地铁",
    ride_hailing: "网约车",
    cycling: "骑行",
  };
  return map[mode] || mode || "-";
}

export function routeReason(mode: string): string {
  const map: Record<string, string> = {
    walking: "已按你的选择改为步行，适合距离较近、节奏更松的安排。",
    driving: "已按你的选择改为驾车，适合多人同行和减少步行。",
    public_transit: "已按你的选择改为公交/地铁，成本更低，适合多人统一出行。",
    ride_hailing: "已按你的选择改为网约车，减少换乘和停车成本。",
    cycling: "已按你的选择改为骑行，适合轻量出行并控制成本。",
  };
  return map[mode] || "已按你的选择更新交通方式。";
}

export function typeLabel(type: string): string {
  const map: Record<string, string> = { travel: "出行", activity: "活动", restaurant: "餐厅" };
  return map[type] || type;
}

export function actionTypeLabel(type: string): string {
  const map: Record<string, string> = {
    book_activity: "预约活动",
    reserve_restaurant: "预订餐厅",
    send_notification: "发送计划",
  };
  return map[type] || type;
}

export function actionLabel(type: string, target: string): string {
  return `${actionTypeLabel(type)}：${target}`;
}
