import { FIELD_HEIGHT, FIELD_WIDTH, type FieldPoint, type FieldTransform } from "./field";
import type { NodeSelection, Play } from "./types";

export function nodeKey(node: NodeSelection): string {
  return `${node.route_index}:${node.point_index}`;
}

export function nodesInBox(play: Play, transform: FieldTransform, start: FieldPoint, end: FieldPoint): NodeSelection[] {
  const left = Math.min(start[0], end[0]),
    right = Math.max(start[0], end[0]);
  const top = Math.min(start[1], end[1]),
    bottom = Math.max(start[1], end[1]);
  return play.routes.flatMap((route, route_index) =>
    route.points.flatMap((point, point_index) => {
      const [x, y] = transform.project(point);
      return x >= left && x <= right && y >= top && y <= bottom ? [{ route_index, point_index }] : [];
    })
  );
}

export function mergeNodeSelections(first: NodeSelection[], second: NodeSelection[]): NodeSelection[] {
  return [...new Map([...first, ...second].map((node) => [nodeKey(node), node])).values()];
}

export function routeWithMostNodes(nodes: NodeSelection[], preferred: number | null): number | null {
  const counts = new Map<number, number>();
  for (const node of nodes) counts.set(node.route_index, (counts.get(node.route_index) ?? 0) + 1);
  let route = preferred,
    maximum = preferred === null ? 0 : counts.get(preferred) ?? 0;
  for (const [index, count] of counts) {
    if (count > maximum) {
      route = index;
      maximum = count;
    }
  }
  return maximum ? route : null;
}

export function groupTranslation(points: FieldPoint[], offset: FieldPoint): FieldPoint {
  if (!points.length) return [0, 0];
  let left = FIELD_WIDTH,
    right = 0,
    top = FIELD_HEIGHT,
    bottom = 0;
  for (const [x, y] of points) {
    left = Math.min(left, x);
    right = Math.max(right, x);
    top = Math.min(top, y);
    bottom = Math.max(bottom, y);
  }
  return [
    Math.max(-left, Math.min(FIELD_WIDTH - right, offset[0])),
    Math.max(-top, Math.min(FIELD_HEIGHT - bottom, offset[1])),
  ];
}
