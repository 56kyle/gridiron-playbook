import { expect, test } from "@playwright/test";
import { readFileSync, readdirSync } from "node:fs";
import type { ShareView } from "../../src/types";
import type {} from "../../test-harness";

const corpus = new URL("../../../rust/core/tests/fixtures/quickshare/", import.meta.url);
const fixtures = readdirSync(corpus).filter((name) => name.endsWith(".gridironshare"));

for (const fixture of fixtures) {
  test(`browser Wasm opens the existing ${fixture} share and preserves an Exact re-share`, async ({ page }) => {
    const bytes = Array.from(readFileSync(new URL(fixture, corpus)));
    const expected = JSON.parse(
      readFileSync(new URL(fixture.replace(".gridironshare", ".json"), corpus), "utf8")
    ) as ShareView;
    await page.goto("./test-harness.html");
    await expect(page.locator("#status")).toHaveText("Ready");
    const actual = await page.evaluate(async (payload) => {
      const decoded = await window.testEngine.inspectShare(new Uint8Array(payload));
      const blank = await window.testEngine.newDocument();
      const imported = await window.testEngine.importShare(blank, new Uint8Array(payload));
      const encoded = await window.testEngine.encodeShare(
        imported.document,
        decoded.plays.map((_, index) => index),
        decoded.kind,
        "exact"
      );
      const reopened = await window.testEngine.inspectShare(encoded);
      return { decoded, reopened };
    }, bytes);
    expect(actual.decoded.kind).toBe(expected.kind);
    expect(actual.decoded.plays).toHaveLength(expected.plays.length);
    const compact =
      /_(?:1mm|1cm)\.gridironshare$/.test(fixture) &&
      !fixture.startsWith("edited_block") &&
      !fixture.startsWith("incomplete_block");
    expected.plays.forEach((play, playIndex) => {
      const decoded = actual.decoded.plays[playIndex]!;
      expect(decoded.play_name).toBe(play.play_name);
      expect(decoded.formation_name).toBe(play.formation_name);
      expect(decoded.routes).toHaveLength(play.routes.length);
      play.routes.forEach((route, routeIndex) => {
        const decodedRoute = decoded.routes[routeIndex]!;
        expect(decodedRoute.slot).toBe(route.slot);
        expect(decodedRoute.points).toHaveLength(route.points.length);
        route.points.forEach((point, pointIndex) => {
          const received = decodedRoute.points[pointIndex]!;
          for (const axis of ["x", "y", "z"] as const) {
            const location = `${fixture} play ${playIndex} route ${routeIndex} point ${pointIndex} ${axis}`;
            const matches = compact
              ? Math.abs(received[axis] - point[axis]) < 5e-9
              : Object.is(received[axis], point[axis]);
            if (!matches) throw new Error(`Decoded coordinate differs: ${location}`);
            const reshared = actual.reopened.plays[playIndex]!.routes[routeIndex]!.points[pointIndex]!;
            if (!Object.is(reshared[axis], received[axis]))
              throw new Error(`Exact re-sharing changed a coordinate: ${location}`);
          }
        });
      });
    });
  });
}
