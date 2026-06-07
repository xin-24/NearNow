import type { PendingAction, Plan, RouteOption, ScheduleItem } from "../api/types";
import { modeLabel, routeReason } from "./labels";

export function selectedRoute(plan: Plan): RouteOption | undefined {
  return plan.route_options.find((r) => r.selected) || plan.route_options[0];
}

export function selectedRouteMode(plan: Plan): string {
  return selectedRoute(plan)?.mode || "";
}

export function addMinutes(timeText: string, minutes: number): string {
  const [hour, minute] = String(timeText || "00:00").split(":").map((v) => Number.parseInt(v, 10));
  const date = new Date(2000, 0, 1, Number.isFinite(hour) ? hour : 0, Number.isFinite(minute) ? minute : 0);
  date.setMinutes(date.getMinutes() + minutes);
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function isRouteRiskNote(note: string): boolean {
  return /路况|步行距离|已选择|骑行|公交\/地铁|交通/.test(note);
}

function routeRiskNote(route: RouteOption): string {
  const prefix = `已选择${modeLabel(route.mode)}，预计 ${route.duration_minutes} 分钟、${route.distance_km} km。`;
  if (route.mode === "driving" || route.mode === "ride_hailing") {
    return `${prefix}出发前建议复查实时路况和上车/停车位置。`;
  }
  if (route.mode === "walking") {
    return `${prefix}${route.distance_km > 2 ? "距离偏长，儿童或老人同行时建议确认体力。" : "适合近距离慢节奏安排。"}`;
  }
  if (route.mode === "cycling") {
    return `${prefix}骑行前请确认同行者安全装备和道路条件。`;
  }
  if (route.mode === "public_transit") {
    return `${prefix}出发前建议复查实时班次和换乘距离。`;
  }
  return prefix;
}

function updateRouteRiskNotes(plan: Plan, route: RouteOption): void {
  const notes = [...(plan.static_risk_notes || plan.risk_notes.filter((n) => !isRouteRiskNote(n)))];
  notes.push(routeRiskNote(route));
  plan.risk_notes = notes.filter(Boolean);
}

function updateRouteSummary(plan: Plan, route: RouteOption): void {
  const lastSchedule = plan.schedule[plan.schedule.length - 1];
  const baseSummary = plan.base_summary || plan.summary;
  const withFinishTime = lastSchedule
    ? baseSummary.replace(/\d{2}:\d{2}\s*前结束/, `${lastSchedule.end_time} 前结束`)
    : baseSummary;
  plan.summary = `${withFinishTime} 当前交通已选择${modeLabel(route.mode)}。`;
}

export function preparePlanForRouteEditing(plan: Plan): void {
  if (plan.route_edit_ready) return;
  plan.route_edit_ready = true;
  plan.base_summary = plan.summary;
  plan.static_risk_notes = plan.risk_notes.filter((n) => !isRouteRiskNote(n));
  if (plan.route_options.length && !plan.route_options.some((r) => r.selected)) {
    plan.route_options[0].selected = true;
  }
}

export function selectRoute(plan: Plan, mode: string): void {
  const route = plan.route_options.find((r) => r.mode === mode);
  if (!route) return;

  const travelIndex = plan.schedule.findIndex((item) => item.type === "travel");
  const travelItem = plan.schedule[travelIndex];
  const previousDuration =
    travelItem?.travel_minutes || selectedRoute(plan)?.duration_minutes || route.duration_minutes;
  const deltaMinutes = route.duration_minutes - previousDuration;

  plan.route_options.forEach((item) => {
    item.selected = item.mode === route.mode;
  });

  if (travelItem) {
    travelItem.end_time = addMinutes(travelItem.start_time, route.duration_minutes);
    travelItem.travel_minutes = route.duration_minutes;
    travelItem.transport_mode = route.mode;
    travelItem.route_geometry = route.route_geometry || travelItem.route_geometry;
    travelItem.reason = routeReason(route.mode);
    if (deltaMinutes) {
      plan.schedule.slice(travelIndex + 1).forEach((item) => {
        item.start_time = addMinutes(item.start_time, deltaMinutes);
        item.end_time = addMinutes(item.end_time, deltaMinutes);
      });
    }
    syncPendingActionTimes(plan);
  }

  updateRouteRiskNotes(plan, route);
  updateRouteSummary(plan, route);
}

export function syncPendingActionTimes(plan: Plan): void {
  const activities = actionScheduleItems(plan.schedule, "book_activity");
  const restaurants = actionScheduleItems(plan.schedule, "reserve_restaurant");
  const usedActivityIndexes = new Set<number>();
  const usedRestaurantIndexes = new Set<number>();

  plan.pending_actions.forEach((action) => {
    if (action.type === "book_activity") {
      const matched = findScheduleItemForAction(action, activities, usedActivityIndexes);
      if (!matched) return;
      action.payload.start_time = matched.item.start_time;
      usedActivityIndexes.add(matched.index);
    }
    if (action.type === "reserve_restaurant") {
      const matched = findScheduleItemForAction(action, restaurants, usedRestaurantIndexes);
      if (!matched) return;
      action.payload.arrival_time = matched.item.start_time;
      usedRestaurantIndexes.add(matched.index);
    }
  });
}

export function removePendingActionForScheduleItem(
  plan: Plan,
  removed: ScheduleItem,
  originalSchedule: ScheduleItem[],
): void {
  const actionType = actionTypeForScheduleItem(removed);
  if (!actionType) return;

  const action = findActionForScheduleItem(
    plan.pending_actions.filter((item) => item.type === actionType),
    removed,
    originalSchedule,
    actionType,
  );
  if (!action) return;

  plan.pending_actions = plan.pending_actions.filter((item) => item.action_id !== action.action_id);
}

function actionTypeForScheduleItem(item: ScheduleItem): PendingAction["type"] | null {
  if (item.type === "activity") return "book_activity";
  if (item.type === "restaurant") return "reserve_restaurant";
  return null;
}

function actionScheduleItems(schedule: ScheduleItem[], actionType: PendingAction["type"]): ScheduleItem[] {
  if (actionType === "book_activity") {
    return schedule.filter((item) => item.type === "activity" && !isGeneratedWrapUpActivity(item));
  }
  if (actionType === "reserve_restaurant") {
    return schedule.filter((item) => item.type === "restaurant");
  }
  return [];
}

function isGeneratedWrapUpActivity(item: ScheduleItem): boolean {
  return item.type === "activity" && item.name.startsWith("餐后") && !item.provider && !item.provider_place_id;
}

function findScheduleItemForAction(
  action: PendingAction,
  items: ScheduleItem[],
  usedIndexes: Set<number>,
): { item: ScheduleItem; index: number } | null {
  const identityIndex = items.findIndex((item, index) => !usedIndexes.has(index) && hasSharedPlaceIdentity(action, item));
  if (identityIndex >= 0) return { item: items[identityIndex], index: identityIndex };

  const targetIndex = items.findIndex((item, index) => !usedIndexes.has(index) && item.name === action.target);
  if (targetIndex >= 0) return { item: items[targetIndex], index: targetIndex };

  const fallbackIndex = items.findIndex((_, index) => !usedIndexes.has(index));
  if (fallbackIndex >= 0) return { item: items[fallbackIndex], index: fallbackIndex };

  return null;
}

function findActionForScheduleItem(
  actions: PendingAction[],
  item: ScheduleItem,
  originalSchedule: ScheduleItem[],
  actionType: PendingAction["type"],
): PendingAction | null {
  const identityMatch = actions.find((action) => hasSharedPlaceIdentity(action, item));
  if (identityMatch) return identityMatch;

  const orderedItems = actionScheduleItems(originalSchedule, actionType);
  const itemIndex = orderedItems.indexOf(item);
  if (itemIndex >= 0 && actions[itemIndex]) return actions[itemIndex];

  return actions.find((action) => action.target === item.name) || null;
}

function hasSharedPlaceIdentity(action: PendingAction, item: ScheduleItem): boolean {
  const itemPlaceId = item.provider_place_id || "";
  if (!itemPlaceId) return false;
  return actionIdentityValues(action).includes(itemPlaceId);
}

function actionIdentityValues(action: PendingAction): string[] {
  return ["provider_place_id", "place_id", "activity_id", "restaurant_id"]
    .map((key) => action.payload[key])
    .filter((value): value is string => typeof value === "string" && value.length > 0);
}

export function inferPartySize(plan: Plan): string {
  const action = plan.pending_actions.find((item) => item.payload && (item.payload as Record<string, unknown>).party_size);
  return action ? String((action.payload as Record<string, unknown>).party_size) : "-";
}

export function parseCompanions(value: string) {
  return String(value || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const parts = line.split(/\s+/).filter(Boolean);
      const [name, relation, ...contactParts] = parts;
      const contactValue = contactParts.join(" ");
      return {
        name: name || "",
        relation: relation || "同行者",
        contact_method: inferContactMethod(contactValue),
        contact_value: contactValue,
      };
    })
    .filter((item) => item.name);
}

function inferContactMethod(value: string): string {
  if (!value) return "";
  if (value.includes("@")) return "email";
  if (/^[+\d][\d\s-]+$/.test(value)) return "phone";
  return "wechat";
}

export function formatCompanionLine(item: { name: string; relation: string; contact_value: string }): string {
  return [item.name, item.relation, item.contact_value].filter(Boolean).join(" ");
}
