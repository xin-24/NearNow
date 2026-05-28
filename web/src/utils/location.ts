export const knownCities = [
  "北京", "上海", "广州", "深圳", "杭州", "成都", "重庆", "天津",
  "南京", "苏州", "武汉", "西安", "厦门", "长沙", "郑州", "青岛",
  "纽约", "旧金山",
];

export function normalizeLocationText(value: string): string {
  return String(value ?? "").replace(/[，,、/|]+/g, " ").replace(/\s+/g, " ").trim();
}

export function inferCityFromLocation(value: string): string {
  const location = normalizeLocationText(value);
  if (!location) return "";
  const knownCity = knownCities.find((city) => location.startsWith(city));
  if (knownCity) return knownCity;
  const cityMatch = location.match(/^([一-龥]{2,8}市)(?:\s|$)/);
  if (cityMatch) return cityMatch[1].replace(/市$/, "");
  return "";
}
