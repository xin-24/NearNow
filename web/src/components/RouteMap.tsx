import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { MouseEvent, PointerEvent, WheelEvent } from "react";
import type { Coordinates, Plan, ScheduleItem } from "../api/types";
import { modeLabel, typeLabel } from "../utils/labels";
import styles from "./RouteMap.module.css";

const TILE_SIZE = 256;
const MAP_WIDTH = 760;
const MAP_HEIGHT = 320;
const MIN_ZOOM = 11;
const MAX_ZOOM = 17;
const PADDING = 46;

interface Point {
  x: number;
  y: number;
}

interface Tile {
  key: string;
  x: number;
  y: number;
  url: string;
}

interface Marker {
  key: string;
  label: string;
  title: string;
  coord: Coordinates;
  kind: "origin" | "activity" | "restaurant";
}

interface MapView {
  zoom: number;
  left: number;
  top: number;
}

interface DragState {
  pointerId: number;
  lastX: number;
  lastY: number;
}

export function RouteMap({ plan }: { plan: Plan }) {
  const svgRef = useRef<SVGSVGElement | null>(null);
  const dragRef = useRef<DragState | null>(null);
  const [dragging, setDragging] = useState(false);
  const travelItems = plan.schedule.filter((item) => item.type === "travel");
  const routeSegments = travelItems
    .map((item) => item.route_geometry || [])
    .filter((segment) => segment.length >= 2);
  const markers = buildMarkers(plan.schedule, routeSegments);
  const allPoints = [...routeSegments.flat(), ...markers.map((marker) => marker.coord)];
  const hasMap = allPoints.length >= 2;
  const resetKey = allPoints.map((point) => `${point.lat.toFixed(5)},${point.lng.toFixed(5)}`).join("|");
  const initialView = useMemo(() => (hasMap ? buildInitialView(allPoints) : defaultView()), [hasMap, resetKey]);
  const minInteractiveZoom = initialView.zoom;
  const [view, setView] = useState<MapView>(initialView);

  useEffect(() => {
    setView(initialView);
  }, [initialView]);

  const zoomAt = useCallback((centerX: number, centerY: number, delta: number) => {
    setView((current) => {
      const nextZoom = clamp(current.zoom + delta, minInteractiveZoom, MAX_ZOOM);
      if (nextZoom === current.zoom) return current;
      const scale = 2 ** (nextZoom - current.zoom);
      return {
        zoom: nextZoom,
        left: (current.left + centerX) * scale - centerX,
        top: (current.top + centerY) * scale - centerY,
      };
    });
  }, [minInteractiveZoom]);

  const eventPoint = useCallback((event: PointerEvent<SVGSVGElement> | WheelEvent<SVGSVGElement> | MouseEvent<SVGSVGElement>) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return { x: MAP_WIDTH / 2, y: MAP_HEIGHT / 2 };
    return {
      x: ((event.clientX - rect.left) / rect.width) * MAP_WIDTH,
      y: ((event.clientY - rect.top) / rect.height) * MAP_HEIGHT,
    };
  }, []);

  const handleWheel = useCallback(
    (event: WheelEvent<SVGSVGElement>) => {
      event.preventDefault();
      const point = eventPoint(event);
      zoomAt(point.x, point.y, event.deltaY < 0 ? 1 : -1);
    },
    [eventPoint, zoomAt],
  );

  const handlePointerDown = useCallback((event: PointerEvent<SVGSVGElement>) => {
    if (event.button !== 0) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = { pointerId: event.pointerId, lastX: event.clientX, lastY: event.clientY };
    setDragging(true);
  }, []);

  const handlePointerMove = useCallback((event: PointerEvent<SVGSVGElement>) => {
    const drag = dragRef.current;
    const rect = svgRef.current?.getBoundingClientRect();
    if (!drag || drag.pointerId !== event.pointerId || !rect) return;
    const deltaX = ((event.clientX - drag.lastX) / rect.width) * MAP_WIDTH;
    const deltaY = ((event.clientY - drag.lastY) / rect.height) * MAP_HEIGHT;
    dragRef.current = { ...drag, lastX: event.clientX, lastY: event.clientY };
    setView((current) => ({
      ...current,
      left: current.left - deltaX,
      top: current.top - deltaY,
    }));
  }, []);

  const handlePointerUp = useCallback((event: PointerEvent<SVGSVGElement>) => {
    if (dragRef.current?.pointerId === event.pointerId) {
      dragRef.current = null;
      setDragging(false);
    }
  }, []);

  const handleDoubleClick = useCallback(
    (event: MouseEvent<SVGSVGElement>) => {
      event.preventDefault();
      const point = eventPoint(event);
      zoomAt(point.x, point.y, 1);
    },
    [eventPoint, zoomAt],
  );

  if (!hasMap) {
    return null;
  }

  const tiles = buildTiles(view, view.zoom);
  const projectedSegments = routeSegments.length
    ? routeSegments.map((segment) => segment.map((point) => project(point, view.zoom, view)))
    : [markers.map((marker) => project(marker.coord, view.zoom, view))];
  const projectedMarkers = markers.map((marker) => ({ ...marker, ...project(marker.coord, view.zoom, view) }));

  return (
    <section className={styles.mapCard}>
      <div className={styles.mapHead}>
        <div>
          <h3>路线地图</h3>
          <p>基于真实坐标展示出发地、活动点、餐厅和行程路线。</p>
        </div>
        <span>{travelItems.length} 段移动</span>
      </div>

      <div className={styles.mapShell}>
        <svg
          ref={svgRef}
          className={`${styles.mapSvg} ${dragging ? styles.dragging : ""}`}
          viewBox={`0 0 ${MAP_WIDTH} ${MAP_HEIGHT}`}
          role="img"
          aria-label="可拖拽缩放的路线地图"
          onWheel={handleWheel}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
          onPointerCancel={handlePointerUp}
          onDoubleClick={handleDoubleClick}
        >
          {tiles.map((tile) => (
            <image
              key={tile.key}
              href={tile.url}
              x={tile.x}
              y={tile.y}
              width={TILE_SIZE}
              height={TILE_SIZE}
              preserveAspectRatio="none"
            />
          ))}
          {projectedSegments.map((segment, index) => (
            <polyline
              key={index}
              className={styles.routeLine}
              points={segment.map((point) => `${point.x},${point.y}`).join(" ")}
            />
          ))}
          {projectedMarkers.map((marker, index) => (
            <g key={marker.key} className={`${styles.marker} ${styles[marker.kind]}`}>
              <circle cx={marker.x} cy={marker.y} r="14" />
              <text x={marker.x} y={marker.y + 5} textAnchor="middle">
                {index + 1}
              </text>
            </g>
          ))}
        </svg>
        <div className={styles.mapControls} aria-label="地图控制">
          <button
            type="button"
            onClick={() => zoomAt(MAP_WIDTH / 2, MAP_HEIGHT / 2, 1)}
            aria-label="放大地图"
          >
            +
          </button>
          <button
            type="button"
            onClick={() => zoomAt(MAP_WIDTH / 2, MAP_HEIGHT / 2, -1)}
            aria-label="缩小地图"
            disabled={view.zoom <= minInteractiveZoom}
          >
            -
          </button>
          <button type="button" onClick={() => setView(initialView)} aria-label="重置地图视图">
            回中
          </button>
        </div>
        <span className={styles.zoomBadge}>Z{view.zoom}</span>
        <div className={styles.legend}>
          {projectedMarkers.map((marker, index) => (
            <span key={marker.key}>
              <b>{index + 1}</b>
              {marker.title}
            </span>
          ))}
        </div>
        <div className={styles.mapHint}>拖拽平移 · 滚轮缩放 · 回中为路线最小视图</div>
        <small>地图 © OpenStreetMap contributors，路线耗时以当前 Provider 返回为准。</small>
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

function defaultView(): MapView {
  return { zoom: MIN_ZOOM, left: 0, top: 0 };
}

function buildInitialView(points: Coordinates[]): MapView {
  const zoom = chooseZoom(points);
  return { zoom, ...buildViewport(points, zoom) };
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

function chooseZoom(points: Coordinates[]): number {
  for (let zoom = MAX_ZOOM; zoom >= MIN_ZOOM; zoom -= 1) {
    const projected = points.map((point) => rawProject(point, zoom));
    const bounds = pointBounds(projected);
    if (bounds.width <= MAP_WIDTH - PADDING * 2 && bounds.height <= MAP_HEIGHT - PADDING * 2) {
      return zoom;
    }
  }
  return MIN_ZOOM;
}

function buildViewport(points: Coordinates[], zoom: number) {
  const projected = points.map((point) => rawProject(point, zoom));
  const bounds = pointBounds(projected);
  const centerX = bounds.minX + bounds.width / 2;
  const centerY = bounds.minY + bounds.height / 2;
  return {
    left: centerX - MAP_WIDTH / 2,
    top: centerY - MAP_HEIGHT / 2,
  };
}

function buildTiles(viewport: { left: number; top: number }, zoom: number): Tile[] {
  const maxTile = 2 ** zoom;
  const startX = Math.floor(viewport.left / TILE_SIZE);
  const endX = Math.floor((viewport.left + MAP_WIDTH) / TILE_SIZE);
  const startY = Math.floor(viewport.top / TILE_SIZE);
  const endY = Math.floor((viewport.top + MAP_HEIGHT) / TILE_SIZE);
  const tiles: Tile[] = [];

  for (let x = startX; x <= endX; x += 1) {
    for (let y = startY; y <= endY; y += 1) {
      if (y < 0 || y >= maxTile) continue;
      const wrappedX = ((x % maxTile) + maxTile) % maxTile;
      tiles.push({
        key: `${zoom}-${wrappedX}-${y}`,
        x: x * TILE_SIZE - viewport.left,
        y: y * TILE_SIZE - viewport.top,
        url: `https://tile.openstreetmap.org/${zoom}/${wrappedX}/${y}.png`,
      });
    }
  }
  return tiles;
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function project(point: Coordinates, zoom: number, viewport: { left: number; top: number }): Point {
  const raw = rawProject(point, zoom);
  return { x: raw.x - viewport.left, y: raw.y - viewport.top };
}

function rawProject(point: Coordinates, zoom: number): Point {
  const scale = TILE_SIZE * 2 ** zoom;
  const lat = Math.max(-85.0511, Math.min(85.0511, point.lat));
  const sinLat = Math.sin((lat * Math.PI) / 180);
  return {
    x: ((point.lng + 180) / 360) * scale,
    y: (0.5 - Math.log((1 + sinLat) / (1 - sinLat)) / (4 * Math.PI)) * scale,
  };
}

function pointBounds(points: Point[]) {
  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  return { minX, minY, width: maxX - minX, height: maxY - minY };
}
