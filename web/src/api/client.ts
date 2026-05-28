import type { ApiResponse, User, Companion, Plan, ExecutionResponse } from "./types";

export class ApiError extends Error {
  code: string;
  recoverable: boolean;
  rawMessage: string;

  constructor(code: string, message: string, recoverable: boolean) {
    super(formatApiErrorMessage(code, message));
    this.name = "ApiError";
    this.code = code;
    this.recoverable = recoverable;
    this.rawMessage = message;
  }
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  const payload: ApiResponse<T> = await response.json();
  if (!payload.success) {
    throw new ApiError(
      payload.error?.code || "REQUEST_FAILED",
      payload.error?.message || "请求失败",
      Boolean(payload.error?.recoverable ?? true),
    );
  }
  return payload.data;
}

function formatApiErrorMessage(code: string, message: string): string {
  if (code === "REAL_PROVIDER_ERROR" && message.includes("高德地图路线规划失败")) {
    return [
      "高德路线服务没有返回可用路线，所以这次规划没有完成。",
      "",
      "为什么后端日志仍然是 200 OK：这表示浏览器成功请求到了后端，后端也正常返回了结果；但结果里的 success=false，表示业务规划失败。前端正是看到这个业务失败后才显示本页。",
      "",
      "常见原因：高德 Web 服务 Key 没有开通对应路线接口；公交/骑行/驾车接口权限或配额受限；公交接口城市参数不匹配；起终点坐标不在可规划范围内；或高德路线服务临时不可用。",
      "",
      `原始错误：${message}`,
    ].join("\n");
  }
  return message;
}

export function createAbortController(): AbortController {
  return new AbortController();
}

export function isAborted(err: unknown): boolean {
  return err instanceof DOMException && err.name === "AbortError";
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
  signal?: AbortSignal,
): Promise<Plan> {
  return request("/api/agent/plan", {
    method: "POST",
    body: JSON.stringify({ message, mode, user_context: userContext, companions }),
    signal,
  });
}

export async function confirmPlan(
  planId: string,
  actionIds: string[],
  routeMode: string,
  signal?: AbortSignal,
): Promise<ExecutionResponse> {
  return request("/api/agent/confirm", {
    method: "POST",
    body: JSON.stringify({
      plan_id: planId,
      confirmed_action_ids: actionIds,
      selected_route_mode: routeMode,
    }),
    signal,
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
