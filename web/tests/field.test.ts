import assert from "node:assert/strict";
import test from "node:test";
import { fieldTransform, insertionOnRoute, markerLabel } from "../src/field";
import type { Formation, Play } from "../src/types";

test("field projection fits routes and inverts screen coordinates", () => {
  const formation: Formation = { name: "Test", positions: [{ slot: 0, label: "QB", x: -600, y: 0 }] };
  const play: Play = {
    formation_name: "Test",
    play_name: "Test",
    routes: [{ slot: 0, points: [{ x: 3000, y: -2000, z: 20 }] }],
  };
  const transform = fieldTransform(play, formation);
  for (const point of [
    { x: -600, y: 0, z: 0 },
    { x: 3000, y: -2000, z: 0 },
  ]) {
    const projected = transform.project(point),
      restored = transform.unproject(projected);
    assert.ok(projected[0] >= 48 && projected[0] <= 752);
    assert.ok(projected[1] >= 48 && projected[1] <= 582);
    assert.ok(Math.abs(restored.x - point.x) < 1e-9);
    assert.ok(Math.abs(restored.y - point.y) < 1e-9);
  }
});

test("node insertion projects onto a nearby segment and otherwise extends the route", () => {
  assert.deepEqual(insertionOnRoute([[100, 100]], [0, 0], [50, 54], 8), { index: 0, position: [52, 52] });
  assert.deepEqual(insertionOnRoute([[100, 100]], [0, 0], [300, 100], 8), { index: 1, position: [300, 100] });
});

test("receiver markers retain short labels", () => {
  assert.equal(markerLabel("WR-L"), "WR");
  assert.equal(markerLabel("WR-R"), "WR");
  assert.equal(markerLabel("Slot 250"), "Slot 250");
});
