import type { Formation, Play, Point } from "./types";

export const FIELD_WIDTH = 800;
export const FIELD_HEIGHT = 630;
export type FieldPoint = readonly [number, number];
export interface FieldTransform {
  scale: number;
  project(point: Pick<Point, "x" | "y">): FieldPoint;
  unproject(point: FieldPoint): Point;
}

export function fieldTransform(play: Play, formation?: Formation): FieldTransform {
  let minX = 0,
    maxX = 0,
    minY = 0,
    maxY = 0;
  for (const point of [...(formation?.positions ?? []), ...play.routes.flatMap((route) => route.points)]) {
    minX = Math.min(minX, point.x);
    maxX = Math.max(maxX, point.x);
    minY = Math.min(minY, point.y);
    maxY = Math.max(maxY, point.y);
  }
  const scale = Math.min(
    (FIELD_WIDTH - 96) / Math.max(3200, maxY - minY),
    (FIELD_HEIGHT - 96) / Math.max(1800, maxX - minX)
  );
  const x = minX / 2 + maxX / 2,
    y = minY / 2 + maxY / 2;
  return {
    scale,
    project: (point) => [FIELD_WIDTH / 2 + (point.y - y) * scale, FIELD_HEIGHT / 2 - (point.x - x) * scale],
    unproject: (point) => ({
      x: x - (point[1] - FIELD_HEIGHT / 2) / scale,
      y: y + (point[0] - FIELD_WIDTH / 2) / scale,
      z: 0,
    }),
  };
}

export function positionLabel(formation: Formation | undefined, slot: number): string {
  return formation?.positions.find((position) => position.slot === slot)?.label ?? `Slot ${slot}`;
}
export function markerLabel(label: string): string {
  return /^WR-[LR]$/.test(label) ? "WR" : label;
}
export function routeColor(label: string): string {
  return label === "QB"
    ? "var(--route-coral)"
    : label === "RB"
    ? "var(--route-blue)"
    : label.startsWith("WR")
    ? "var(--route-yellow)"
    : ["LT", "RT", "T"].includes(label)
    ? "var(--route-white)"
    : "var(--muted)";
}

export function insertionOnRoute(
  points: FieldPoint[],
  origin: FieldPoint | undefined,
  position: FieldPoint,
  radius: number
): { index: number; position: FieldPoint } {
  let nearest = { index: points.length, position };
  let distance = radius;
  for (let index = origin ? 0 : 1; index < points.length; index++) {
    const start = points[index - 1] ?? origin;
    const end = points[index]!;
    if (!start) continue;
    const dx = end[0] - start[0],
      dy = end[1] - start[1];
    const length = dx * dx + dy * dy;
    if (!length) continue;
    const t = ((position[0] - start[0]) * dx + (position[1] - start[1]) * dy) / length;
    if (t < 0 || t > 1) continue;
    const candidate: FieldPoint = [start[0] + t * dx, start[1] + t * dy];
    const candidateDistance = Math.hypot(candidate[0] - position[0], candidate[1] - position[1]);
    if (candidateDistance < distance) {
      distance = candidateDistance;
      nearest = { index, position: candidate };
    }
  }
  return nearest;
}
