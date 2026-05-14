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

export function RouteMap({ plan }: { plan: Plan }) {
  const travelItems = plan.schedule.filter((item) => item.type === "travel");
  const routeSegments = travelItems
    .map((item) => item.route_geometry || [])
    .filter((segment) => segment.length >= 2);
  const markers = buildMarkers(plan.schedule, routeSegments);
  const allPoints = [...routeSegments.flat(), ...markers.map((marker) => marker.coord)];

  if (allPoints.length < 2) {
    return null;
  }

  const zoom = chooseZoom(allPoints);
  const viewport = buildViewport(allPoints, zoom);
  const tiles = buildTiles(viewport, zoom);
  const projectedSegments = routeSegments.length
    ? routeSegments.map((segment) => segment.map((point) => project(point, zoom, viewport)))
    : [markers.map((marker) => project(marker.coord, zoom, viewport))];
  const projectedMarkers = markers.map((marker) => ({ ...marker, ...project(marker.coord, zoom, viewport) }));

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
        <svg className={styles.mapSvg} viewBox={`0 0 ${MAP_WIDTH} ${MAP_HEIGHT}`} role="img" aria-label="路线地图">
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
        <div className={styles.legend}>
          {projectedMarkers.map((marker, index) => (
            <span key={marker.key}>
              <b>{index + 1}</b>
              {marker.title}
            </span>
          ))}
        </div>
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
