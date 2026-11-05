import { expect, test } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";
import { bookFile, clickSvg, hoverSvg, ready, waitForRecovery } from "./helpers";

async function openRoutes(page: Page): Promise<void> {
  const file = await bookFile("Selection", 1);
  const document = JSON.parse(file.buffer.toString("utf8"));
  document.root.properties.CustomPlays_0[0].FormationName_0 = "Twins Right";
  document.root.properties.CustomPlays_0[0].Routes_0 = [
    { Slot_0: 5, Points_0: [200, 800, 1000].map((x) => ({ X_0: x, Y_0: -700, Z_0: 12 })) },
    { Slot_0: 6, Points_0: [200, 800].map((x) => ({ X_0: x, Y_0: 700, Z_0: 30 })) },
  ];
  await page.goto("./");
  await ready(page);
  await page.getByTestId("open-files").setInputFiles({ ...file, buffer: Buffer.from(JSON.stringify(document)) });
  await expect(page.getByRole("listbox", { name: "Routes", exact: true }).getByRole("option")).toHaveCount(2);
}

async function routePoints(page: Page, route: number): Promise<number[][]> {
  const raw = await page
    .getByTestId("play-field")
    .locator(`[data-route-index="${route}"] polyline`)
    .last()
    .getAttribute("points");
  if (!raw) throw new Error("Route has no geometry.");
  return raw
    .split(" ")
    .slice(1)
    .map((point) => point.split(",").map(Number));
}

function selectedNodes(page: Page): Locator {
  return page.getByTestId("play-field").locator('[data-point-index][aria-pressed="true"]');
}

async function selectUpperNodes(page: Page): Promise<void> {
  const first = await routePoints(page, 0),
    second = await routePoints(page, 1);
  await hoverSvg(page, first[0]![0]! - 25, first[2]![1]! - 25);
  await page.mouse.down();
  await hoverSvg(page, second[0]![0]! + 25, first[1]![1]! + 25);
  await expect(page.locator("[data-selection-box]")).toBeVisible();
  await expect(selectedNodes(page)).toHaveCount(3);
  await page.mouse.up();
  await expect(page.locator("[data-selection-box]")).toHaveCount(0);
  await expect(page.getByTestId("route-0")).toHaveAttribute("aria-selected", "true");
}

async function moveNode(page: Page, node: Locator, dx: number, dy: number): Promise<void> {
  const bounds = await node.boundingBox();
  if (!bounds) throw new Error("Node is not visible.");
  const x = bounds.x + bounds.width / 2,
    y = bounds.y + bounds.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + dx, y + dy, { steps: 4 });
}

async function nodePositions(nodes: Locator): Promise<number[][]> {
  return nodes.evaluateAll((elements) =>
    elements.map((element) => {
      const matrix = (element as SVGGraphicsElement).transform.baseVal.consolidate()!.matrix;
      return [matrix.e, matrix.f];
    })
  );
}

for (const selection of ["sidebar", "field"] as const) {
  test(`Delete removes the whole route selected in the ${selection} and supports undo`, async ({ page }) => {
    await openRoutes(page);
    if (selection === "sidebar") await page.getByTestId("route-0").click();
    else {
      const points = await routePoints(page, 0);
      await clickSvg(page, points[0]![0]!, (points[0]![1]! + points[1]![1]!) / 2);
    }
    await expect(selectedNodes(page)).toHaveCount(0);
    const remaining = await page.getByTestId("route-1").innerText();
    await page.keyboard.press("Delete");
    await expect(page.getByTestId("route-1")).toHaveCount(0);
    await page.keyboard.press("Delete");
    await expect(page.getByTestId("route-0")).toBeVisible();
    await expect(page.getByTestId("route-0")).toHaveText(remaining, { useInnerText: true });
    await page.keyboard.press("Control+z");
    await expect(page.getByTestId("route-1")).toBeVisible();
    await page.keyboard.press("Control+Shift+z");
    await expect(page.getByTestId("route-1")).toHaveCount(0);
  });
}

test("marquee selection moves nodes across routes together as one undoable edit", async ({ page }) => {
  await openRoutes(page);
  await selectUpperNodes(page);
  const selected = selectedNodes(page);
  const before = await nodePositions(selected);
  const paths = [await routePoints(page, 0), await routePoints(page, 1)];
  await moveNode(page, selected.first(), 30, 20);
  const preview = await nodePositions(selected);
  const delta = [preview[0]![0]! - before[0]![0]!, preview[0]![1]! - before[0]![1]!];
  expect(Math.hypot(...delta)).toBeGreaterThan(10);
  for (let index = 1; index < before.length; index++) {
    expect(preview[index]![0]! - before[index]![0]!).toBeCloseTo(delta[0]!, 4);
    expect(preview[index]![1]! - before[index]![1]!).toBeCloseTo(delta[1]!, 4);
  }
  await page.mouse.up();
  await expect(page.getByRole("button", { name: "Undo", exact: true })).toBeEnabled();
  await waitForRecovery(page);
  await expect(selected).toHaveCount(3);
  const moved = [await routePoints(page, 0), await routePoints(page, 1)];
  expect(moved).not.toEqual(paths);
  await page.keyboard.press("Control+z");
  await expect(page.getByRole("button", { name: "Undo", exact: true })).toBeDisabled();
  expect([await routePoints(page, 0), await routePoints(page, 1)]).toEqual(paths);
  await page.keyboard.press("Control+Shift+z");
  await expect(page.getByRole("button", { name: "Redo", exact: true })).toBeDisabled();
  expect([await routePoints(page, 0), await routePoints(page, 1)]).toEqual(moved);
});

test("marquee deletion removes only selected nodes and can delete all routes", async ({ page }) => {
  await openRoutes(page);
  await selectUpperNodes(page);
  await page.keyboard.press("Delete");
  await expect(page.getByRole("button", { name: "Undo", exact: true })).toBeEnabled();
  expect(await routePoints(page, 0)).toHaveLength(1);
  expect(await routePoints(page, 1)).toHaveLength(1);
  await page.keyboard.press("Control+z");
  await expect(page.getByRole("button", { name: "Undo", exact: true })).toBeDisabled();
  expect(await routePoints(page, 0)).toHaveLength(3);
  expect(await routePoints(page, 1)).toHaveLength(2);
  await hoverSvg(page, 10, 10);
  await page.mouse.down();
  await hoverSvg(page, 790, 620);
  await page.mouse.up();
  await expect(selectedNodes(page)).toHaveCount(5);
  await page.keyboard.press("Delete");
  await expect(page.getByTestId("route-0")).toHaveCount(0);
  await page.keyboard.press("Control+z");
  await expect(page.getByTestId("route-1")).toBeVisible();
});

test("Shift toggles nodes, Escape cancels a group drag, and text Delete leaves routes intact", async ({ page }) => {
  await openRoutes(page);
  await selectUpperNodes(page);
  const node = page.getByTestId("play-field").locator('[data-node-route="0"] [data-point-index="1"]');
  await node.click({ modifiers: ["Shift"] });
  await expect(selectedNodes(page)).toHaveCount(2);
  await node.click({ modifiers: ["Shift"] });
  await expect(selectedNodes(page)).toHaveCount(3);
  const paths = [await routePoints(page, 0), await routePoints(page, 1)];
  await moveNode(page, node, 40, -20);
  await page.keyboard.press("Escape");
  await page.mouse.up();
  expect([await routePoints(page, 0), await routePoints(page, 1)]).toEqual(paths);
  await expect(page.getByRole("button", { name: "Undo", exact: true })).toBeDisabled();
  await expect(selectedNodes(page)).toHaveCount(3);
  await page.getByLabel("Play name", { exact: true }).focus();
  await page.keyboard.press("Home");
  await page.keyboard.press("Delete");
  expect([await routePoints(page, 0), await routePoints(page, 1)]).toEqual(paths);
});

test("Shift-drag adds nodes and Escape restores the selection before a box drag", async ({ page }) => {
  await openRoutes(page);
  await selectUpperNodes(page);
  const first = (await routePoints(page, 0))[0]!;
  await page.keyboard.down("Shift");
  await hoverSvg(page, first[0]! - 25, first[1]! - 25);
  await page.mouse.down();
  await hoverSvg(page, first[0]! + 25, first[1]! + 25);
  await page.mouse.up();
  await page.keyboard.up("Shift");
  await expect(selectedNodes(page)).toHaveCount(4);
  await hoverSvg(page, 10, 10);
  await page.mouse.down();
  await hoverSvg(page, 50, 50);
  await expect(selectedNodes(page)).toHaveCount(0);
  await page.keyboard.press("Escape");
  await page.mouse.up();
  await expect(selectedNodes(page)).toHaveCount(4);
  await expect(page.locator("[data-selection-box]")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Undo", exact: true })).toBeDisabled();
});

test("a moved group remains selected and can be deleted immediately", async ({ page }) => {
  await openRoutes(page);
  await selectUpperNodes(page);
  await moveNode(page, selectedNodes(page).first(), 30, 20);
  await page.mouse.up();
  await expect(page.getByRole("button", { name: "Undo", exact: true })).toBeEnabled();
  await waitForRecovery(page);
  await expect(selectedNodes(page)).toHaveCount(3);
  await expect(page.getByTestId("play-field")).toBeFocused();
  await page.keyboard.press("Delete");
  await expect
    .poll(async () => [(await routePoints(page, 0)).length, (await routePoints(page, 1)).length])
    .toEqual([1, 1]);
});
