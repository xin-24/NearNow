import { useEffect, useMemo, useRef, useState } from "react";
import type { Coordinates, Plan, ScheduleItem } from "../api/types";
import { modeLabel, typeLabel } from "../utils/labels";
import styles from "./RouteMap.module.css";

const MAX_FIT_ZOOM = 17;
const AMAP_SCRIPT_TIMEOUT_MS = 12000;

type LoadState = "idle" | "loading" | "ready" | "error" | "missing-key";
type AMapPath = [number, number][];
type AMapOverlay = unknown;

interface Marker {
  key: string;
  label: string;
  title: string;
  coord: Coordinates;
  kind: "origin" | "activity" | "restaurant";
}

interface AMapMap {
  add(overlays: AMapOverlay | AMapOverlay[]): void;
  addControl(control: unknown): void;
  setFitView(overlays?: AMapOverlay[], immediately?: boolean, avoid?: number[], maxZoom?: number): void;
  destroy(): void;
}

interface AMapNamespace {
  Map: new (container: HTMLElement, options: Record<string, unknown>) => AMapMap;
  Marker: new (options: Record<string, unknown>) => AMapOverlay;
  Polyline: new (options: Record<string, unknown>) => AMapOverlay;
  Pixel: new (x: number, y: number) => unknown;
  Scale?: new (options?: Record<string, unknown>) => unknown;
  ControlBar?: new (options?: Record<string, unknown>) => unknown;
  plugin?: (names: string | string[], callback: () => void) => void;
}

declare global {
  interface Window {
    AMap?: AMapNamespace;
    _AMapSecurityConfig?: {
      securityJsCode?: string;
      serviceHost?: string;
    };
  }
}

let amapLoadPromise: Promise<AMapNamespace> | null = null;
let amapScriptEl: HTMLScriptElement | null = null;

export function RouteMap({ plan }: { plan: Plan }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<AMapMap | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [retryNonce, setRetryNonce] = useState(0);
  const apiKey = cleanEnvValue(import.meta.env.VITE_AMAP_JS_API_KEY || import.meta.env.VITE_AMAP_WEB_JS_KEY || "");
  const securityJsCode = cleanEnvValue(import.meta.env.VITE_AMAP_SECURITY_JS_CODE || "");
  const serviceHost = normalizeServiceHost(cleanEnvValue(import.meta.env.VITE_AMAP_SERVICE_HOST || ""));

  const travelItems = plan.schedule.filter((item) => item.type === "travel");
  const routeSegments = travelItems
    .map((item) => item.route_geometry || [])
    .filter((segment) => segment.length >= 2);
  const markers = buildMarkers(plan.schedule, routeSegments);
  const allPoints = [...routeSegments.flat(), ...markers.map((marker) => marker.coord)];
  const hasMap = allPoints.length >= 2;
  const resetKey = allPoints.map((point) => `${point.lat.toFixed(5)},${point.lng.toFixed(5)}`).join("|");
  const markerKey = markers.map((marker) => `${marker.kind}:${marker.title}:${marker.coord.lat},${marker.coord.lng}`).join("|");
  const pathKey = routeSegments
    .map((segment) => segment.map((point) => `${point.lat},${point.lng}`).join(";"))
    .join("|");

  const mapData = useMemo(
    () => ({
      paths: routeSegments.map(toAmapPath),
      markers,
    }),
    [markerKey, pathKey],
  );

  useEffect(() => {
    if (!hasMap) return;
    if (!apiKey) {
      setLoadState("missing-key");
      return;
    }

    let cancelled = false;
    setLoadState("loading");
    loadAmap(apiKey, { securityJsCode, serviceHost })
      .then((AMap) => {
        if (cancelled || !containerRef.current) return;
        const map = new AMap.Map(containerRef.current, {
          viewMode: "2D",
          zoom: 13,
          resizeEnable: true,
          dragEnable: true,
          zoomEnable: true,
          doubleClickZoom: true,
        });
        mapRef.current = map;

        const overlays: AMapOverlay[] = [];
        for (const path of mapData.paths) {
          overlays.push(
            new AMap.Polyline({
              path,
              strokeColor: "#2563eb",
              strokeWeight: 7,
              strokeOpacity: 0.88,
              lineJoin: "round",
              lineCap: "round",
              zIndex: 20,
              showDir: true,
            }),
          );
        }
        mapData.markers.forEach((marker, index) => {
          overlays.push(
            new AMap.Marker({
              position: toAmapPoint(marker.coord),
              title: `${marker.label}: ${marker.title}`,
              offset: new AMap.Pixel(-14, -14),
              content: markerContent(marker, index),
              zIndex: 40 + index,
            }),
          );
        });
        map.add(overlays);
        map.setFitView(overlays, false, [46, 46, 46, 46], MAX_FIT_ZOOM);
        addControls(AMap, map);
        setLoadState("ready");
      })
      .catch(() => {
        if (!cancelled) setLoadState("error");
      });

    return () => {
      cancelled = true;
      mapRef.current?.destroy();
      mapRef.current = null;
    };
  }, [apiKey, securityJsCode, serviceHost, hasMap, resetKey, mapData, retryNonce]);

  if (!hasMap) {
    return null;
  }

  return (
    <section className={styles.mapCard}>
      <div className={styles.mapHead}>
        <div>
          <h3>路线地图</h3>
          <p>基于高德地图展示出发地、活动点、餐厅和行程路线。</p>
        </div>
        <span>{travelItems.length} 段移动</span>
      </div>

      <div className={styles.mapShell}>
        <div ref={containerRef} className={styles.amapCanvas} aria-label="高德路线地图" />
        {loadState !== "ready" ? <MapStatus state={loadState} onRetry={() => setRetryNonce((current) => current + 1)} /> : null}
        <div className={styles.legend}>
          {markers.map((marker, index) => (
            <span key={marker.key}>
              <b>{index + 1}</b>
              {marker.title}
            </span>
          ))}
        </div>
        <div className={styles.mapHint}>拖拽平移 · 滚轮缩放 · 双击放大</div>
        <small>地图 © 高德地图，路线耗时以当前 Provider 返回为准。</small>
      </div>

      <div className={styles.routeDetails}>
        {travelItems.map((item, index) => (
          <article key={`${item.name}-${index}`}>
            <span>{modeLabel(item.transport_mode || "")}</span>
            <strong>{item.name}</strong>
            <p>
              {item.travel_minutes || 0} 分钟
              {item.route_geometry?.length ? ` · ${item.route_geometry.length} 个路线点` : ""}
            </p>
          </article>
        ))}
      </div>
    </section>
  );
}

function MapStatus({ state, onRetry }: { state: LoadState; onRetry: () => void }) {
  const content = {
    idle: {
      title: "准备加载高德地图",
      detail: "路线数据已生成，正在准备地图容器。",
    },
    loading: {
      title: "正在加载高德地图",
      detail: "稍等片刻，地图底图和路线标记会自动显示。",
    },
    ready: null,
    error: {
      title: "高德地图加载失败",
      detail:
        "请确认 VITE_AMAP_JS_API_KEY 是有效的高德 Web 端 JSAPI Key，不是 Web 服务/Android/iOS Key；如果控制台出现 <AMap JSAPI> Error key!，说明当前 Key 本身被高德拒绝；同时确认 localhost 或 127.0.0.1 已加入域名白名单，VITE_AMAP_SECURITY_JS_CODE 有效，或 VITE_AMAP_SERVICE_HOST 指向可用的 /_AMapService 代理。",
    },
    "missing-key": {
      title: "还没有配置前端地图 Key",
      detail:
        "后端可以生成路线，但浏览器显示高德底图需要单独配置高德 Web 端 JSAPI Key：VITE_AMAP_JS_API_KEY。填入 .env.local 后重启前端服务即可显示地图。",
    },
  }[state];
  if (!content) return null;
  return (
    <div className={styles.mapStatus}>
      <strong>{content.title}</strong>
      <span>{content.detail}</span>
      {state === "error" ? (
        <button type="button" onClick={onRetry}>
          重试加载地图
        </button>
      ) : null}
    </div>
  );
}

function buildMarkers(schedule: ScheduleItem[], routeSegments: Coordinates[][]): Marker[] {
  const markers: Marker[] = [];
  const firstPoint = routeSegments[0]?.[0];
  if (firstPoint) {
    markers.push({ key: "origin", label: "出发", title: "出发地", coord: firstPoint, kind: "origin" });
  }

  const seen = new Set<string>();
  for (const item of schedule) {
    if (!item.coordinates || item.type === "travel") continue;
    const key = `${item.coordinates.lat.toFixed(5)},${item.coordinates.lng.toFixed(5)}`;
    if (seen.has(key)) continue;
    seen.add(key);
    markers.push({
      key: `${item.type}-${key}`,
      label: typeLabel(item.type),
      title: item.name,
      coord: item.coordinates,
      kind: item.type === "restaurant" ? "restaurant" : "activity",
    });
  }
  return markers;
}

function loadAmap(
  apiKey: string,
  security: { securityJsCode?: string; serviceHost?: string },
): Promise<AMapNamespace> {
  if (window.AMap) return Promise.resolve(window.AMap);
  applyAmapSecurityConfig(security);
  if (amapLoadPromise) return amapLoadPromise;

  amapLoadPromise = new Promise<AMapNamespace>((resolve, reject) => {
    if (amapScriptEl?.parentNode) {
      amapScriptEl.remove();
    }

    const script = document.createElement("script");
    amapScriptEl = script;
    const params = new URLSearchParams({
      v: "2.0",
      key: apiKey,
      plugin: "AMap.Scale,AMap.ControlBar",
    });
    script.src = `https://webapi.amap.com/maps?${params.toString()}`;
    script.async = true;
    script.dataset.amapJsapi = "true";

    const timeoutId = window.setTimeout(() => {
      fail(new Error("AMap script load timed out"));
    }, AMAP_SCRIPT_TIMEOUT_MS);

    const cleanup = () => {
      window.clearTimeout(timeoutId);
      script.onload = null;
      script.onerror = null;
    };

    const fail = (error: Error) => {
      cleanup();
      if (amapScriptEl === script) {
        amapScriptEl = null;
      }
      script.remove();
      reject(error);
    };

    script.onload = () => {
      cleanup();
      if (window.AMap) {
        resolve(window.AMap);
      } else {
        fail(new Error("AMap global was not created"));
      }
    };
    script.onerror = () => fail(new Error("AMap script failed to load"));
    document.head.appendChild(script);
  }).catch((error) => {
    amapLoadPromise = null;
    throw error;
  });
  return amapLoadPromise;
}

function applyAmapSecurityConfig(security: { securityJsCode?: string; serviceHost?: string }): void {
  const serviceHost = normalizeServiceHost(cleanEnvValue(security.serviceHost || ""));
  const securityJsCode = cleanEnvValue(security.securityJsCode || "");
  const nextConfig: Window["_AMapSecurityConfig"] = {};

  if (serviceHost) {
    nextConfig.serviceHost = serviceHost;
  }
  if (securityJsCode) {
    nextConfig.securityJsCode = securityJsCode;
  }

  if (Object.keys(nextConfig).length) {
    window._AMapSecurityConfig = nextConfig;
  } else {
    delete window._AMapSecurityConfig;
  }
}

function normalizeServiceHost(value: string): string {
  const trimmed = cleanEnvValue(value).replace(/\/+$/, "");
  if (!trimmed) return "";
  return trimmed.endsWith("/_AMapService") ? trimmed : `${trimmed}/_AMapService`;
}

function cleanEnvValue(value: string): string {
  const trimmed = value.trim();
  if (!trimmed || isPlaceholderValue(trimmed)) return "";
  return trimmed;
}

function isPlaceholderValue(value: string): boolean {
  const normalized = value.toLowerCase().replace(/[\s_{}[\]'"`<>]+/g, "-");
  return (
    normalized === "your-key" ||
    normalized === "your-api-key" ||
    normalized === "your-jsapi-key" ||
    normalized === "your-security-js-code" ||
    normalized === "securityjscode" ||
    normalized === "your-service-host" ||
    normalized === "placeholder" ||
    normalized.includes("your-") ||
    normalized.includes("example") ||
    normalized.includes("replace-me") ||
    normalized.includes("填入") ||
    normalized.includes("填写") ||
    normalized.includes("你的") ||
    normalized.includes("申请的")
  );
}

function addControls(AMap: AMapNamespace, map: AMapMap): void {
  AMap.plugin?.(["AMap.Scale", "AMap.ControlBar"], () => {
    if (AMap.Scale) {
      map.addControl(new AMap.Scale());
    }
    if (AMap.ControlBar) {
      map.addControl(new AMap.ControlBar({ position: { right: "12px", top: "12px" } }));
    }
  });
}

function markerContent(marker: Marker, index: number): string {
  const classes = [
    styles.markerPin,
    marker.kind === "origin" ? styles.originPin : marker.kind === "restaurant" ? styles.restaurantPin : styles.activityPin,
  ].join(" ");
  return `<div class="${classes}" title="${escapeHtml(marker.label)}: ${escapeHtml(marker.title)}">${index + 1}</div>`;
}

function toAmapPath(segment: Coordinates[]): AMapPath {
  return segment.map(toAmapPoint);
}

function toAmapPoint(point: Coordinates): [number, number] {
  return [point.lng, point.lat];
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => {
    const map: Record<string, string> = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    };
    return map[char] || char;
  });
}
