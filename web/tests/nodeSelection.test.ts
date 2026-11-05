import assert from "node:assert/strict";
import test from "node:test";
import { fieldTransform } from "../src/field";
import { groupTranslation, mergeNodeSelections, nodesInBox, routeWithMostNodes } from "../src/nodeSelection";
import type { Play } from "../src/types";

test("box selection includes boundary nodes across routes in either drag direction", () => {
  const play: Play = {
    formation_name: "Unknown",
    play_name: "Box",
    routes: [
      {
        slot: 5,
        points: [
          { x: 0, y: 0, z: 0 },
          { x: 500, y: 100, z: 12 },
        ],
      },
      {
        slot: 6,
        points: [
          { x: 1000, y: 200, z: 10 },
          { x: -500, y: 1000, z: 0 },
        ],
      },
    ],
  };
  const transform = fieldTransform(play);
  const first = transform.project(play.routes[0]!.points[1]!);
  const last = transform.project(play.routes[1]!.points[0]!);
  const expected = [
    { route_index: 0, point_index: 1 },
    { route_index: 1, point_index: 0 },
  ];
  assert.deepEqual(nodesInBox(play, transform, first, last), expected);
  assert.deepEqual(nodesInBox(play, transform, last, first), expected);
  assert.deepEqual(nodesInBox(play, transform, [0, 0], [10, 10]), []);
});

test("the route with most selected nodes is active, with existing route winning ties", () => {
  const nodes = [
    { route_index: 1, point_index: 0 },
    { route_index: 0, point_index: 1 },
  ];
  assert.equal(routeWithMostNodes(nodes, 0), 0);
  assert.equal(routeWithMostNodes(nodes, null), 1);
  assert.equal(routeWithMostNodes([...nodes, { route_index: 1, point_index: 2 }], 0), 1);
  assert.equal(routeWithMostNodes([], 0), null);
});

test("additive box selection preserves existing nodes without duplicates", () => {
  const first = [
    { route_index: 0, point_index: 1 },
    { route_index: 1, point_index: 0 },
  ];
  const last = { route_index: 1, point_index: 2 };
  assert.deepEqual(mergeNodeSelections(first, [first[0]!, last]), [...first, last]);
});

test("group movement clamps the whole selection without changing relative spacing", () => {
  assert.deepEqual(
    groupTranslation(
      [
        [10, 20],
        [790, 610],
      ],
      [100, 100]
    ),
    [10, 20]
  );
  assert.deepEqual(
    groupTranslation(
      [
        [10, 20],
        [790, 610],
      ],
      [-100, -100]
    ),
    [-10, -20]
  );
  assert.deepEqual(
    groupTranslation(
      [
        [10, 20],
        [790, 610],
      ],
      [5, -4]
    ),
    [5, -4]
  );
  assert.deepEqual(groupTranslation([], [10, 10]), [0, 0]);
});
