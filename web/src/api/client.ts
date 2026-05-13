import type { ApiResponse, User, Companion, Plan, ExecutionResponse } from "./types";

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  const payload: ApiResponse<T> = await response.json();
  if (!payload.success) {
    throw new Error(payload.error?.message || "请求失败");
  }
  return payload.data;
}

export async function login(username: string, password: string, displayName: string): Promise<{ user: User }> {
  return request("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password, display_name: displayName }),
  });
}

export async function logout(): Promise<void> {
  await request("/api/auth/logout", { method: "POST" });
}

export async function checkSession(): Promise<{ authenticated: boolean; user?: User }> {
  return request("/api/auth/me");
}

export async function loadCompanions(): Promise<Companion[]> {
  return request("/api/companions");
}

export async function generatePlan(
  message: string,
  mode: string,
  userContext: Record<string, unknown>,
  companions: Companion[],
): Promise<Plan> {
  return request("/api/agent/plan", {
    method: "POST",
    body: JSON.stringify({ message, mode, user_context: userContext, companions }),
  });
}

export async function confirmPlan(
  planId: string,
  actionIds: string[],
  routeMode: string,
): Promise<ExecutionResponse> {
  return request("/api/agent/confirm", {
    method: "POST",
    body: JSON.stringify({
      plan_id: planId,
      confirmed_action_ids: actionIds,
      selected_route_mode: routeMode,
    }),
  });
}

export async function reverseGeocode(
  coordinates: { lat: number; lng: number },
  precision: string,
): Promise<{
  city: string;
  district: string;
  landmark: string;
  formatted_address: string;
  source: string;
  confidence: string;
}> {
  return request("/api/location/reverse-geocode", {
    method: "POST",
    body: JSON.stringify({ coordinates, precision }),
  });
}
