import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { clickSvg, hoverSvg, openBook, waitForRecovery } from "./helpers";

async function startCenterRoute(page: Page): Promise<void> {
  await page.goto("./");
  await openBook(page, "Routes", 1);
  await page.getByTestId("play-field").locator('[data-lineup-slot="1"]').click();
  await expect(page.getByRole("button", { name: "Finish route", exact: true })).toBeVisible();
}

function coordinates(points: string | null): number[] {
  if (points === null) throw new Error("Route has no SVG points.");
  return points
    .trim()
    .split(/[\s,]+/)
    .map(Number);
}

test("route previews follow the pointer and draft keyboard edits survive refresh", async ({ page }) => {
  await startCenterRoute(page);
  const field = page.getByTestId("play-field");
  const preview = field.locator("[data-draft-preview]");
  const path = field.locator("[data-draft-path]");
  await hoverSvg(page, 320, 190);
  await expect(preview).toBeVisible();
  const anticipated = coordinates(await preview.getAttribute("points")).slice(-2);
  await clickSvg(page, 320, 190);
  const placed = coordinates(await path.getAttribute("points")).slice(-2);
  expect(placed[0]).toBeCloseTo(anticipated[0]!, 5);
  expect(placed[1]).toBeCloseTo(anticipated[1]!, 5);
  const onePoint = await path.getAttribute("points");
  await hoverSvg(page, 400, 140);
  await expect(preview).toBeVisible();
  await clickSvg(page, 400, 140);
  const twoPoints = await path.getAttribute("points");
  expect(twoPoints).not.toBe(onePoint);
  await page.keyboard.press("Control+z");
  await expect(path).toHaveAttribute("points", onePoint!);
  await page.keyboard.press("Control+Shift+z");
  await expect(path).toHaveAttribute("points", twoPoints!);
  await waitForRecovery(page);
  await page.reload();
  await expect(page.getByRole("button", { name: "Finish route", exact: true })).toBeEnabled();
  const recovered = coordinates(await path.getAttribute("points"));
  const original = coordinates(twoPoints);
  expect(recovered).toHaveLength(original.length);
  for (let index = 0; index < original.length; index++) expect(recovered[index]).toBeCloseTo(original[index]!, 5);
  await field.focus();
  await page.keyboard.press("Enter");
  await expect(path).toHaveCount(0);
  await expect(page.getByTestId("route-5")).toBeVisible();
  await expect(field.locator("[data-point-index]")).toHaveCount(2);
});

test("cancel abandons a draft without creating a route", async ({ page }) => {
  await startCenterRoute(page);
  await clickSvg(page, 320, 190);
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("play-field").locator("[data-draft-path]")).toHaveCount(0);
  await expect(page.getByTestId("route-5")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Undo", exact: true })).toBeDisabled();
});

test("route nodes can be inserted, deleted, moved and blocked without inflating displayed yards", async ({ page }) => {
  await startCenterRoute(page);
  await clickSvg(page, 320, 190);
  await clickSvg(page, 400, 140);
  await page.keyboard.press("Enter");
  const field = page.getByTestId("play-field");
  const nodes = field.locator("[data-point-index]");
  await expect(nodes).toHaveCount(2);
  const before = await page.getByTestId("route-5").innerText();
  await page.getByRole("button", { name: "Add block", exact: true }).click();
  await expect(nodes).toHaveCount(30);
  await expect(page.getByTestId("route-5")).toHaveText(before, { useInnerText: true });
  await expect(field.locator('[data-route-index="5"] polyline').last()).not.toHaveAttribute("marker-end", /.+/);
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await page.getByTestId("route-5").click();
  await expect(nodes).toHaveCount(2);

  await page.getByRole("button", { name: "Add node", exact: true }).click();
  const midpoint = await nodes.evaluateAll((elements) => {
    const positions = elements.map((element) => {
      const matrix = (element as SVGGraphicsElement).transform.baseVal.consolidate()?.matrix;
      if (!matrix) throw new Error("Node has no field transform.");
      return { x: matrix.e, y: matrix.f };
    });
    return { x: (positions[0]!.x + positions[1]!.x) / 2, y: (positions[0]!.y + positions[1]!.y) / 2 };
  });
  await clickSvg(page, midpoint.x, midpoint.y);
  await expect(nodes).toHaveCount(3);
  await nodes.nth(1).focus();
  await page.keyboard.press("Delete");
  await expect(nodes).toHaveCount(2);

  const node = nodes.nth(1);
  const origin = await node.getAttribute("transform");
  const bounds = await node.boundingBox();
  if (!bounds) throw new Error("Selected route node has no bounds.");
  await page.mouse.move(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
  await page.mouse.down();
  await page.mouse.move(bounds.x + bounds.width / 2 + 35, bounds.y + bounds.height / 2 - 15, { steps: 4 });
  await page.mouse.up();
  await expect(node).not.toHaveAttribute("transform", origin!);
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await page.getByTestId("route-5").click();
  await expect(node).toHaveAttribute("transform", origin!);

  await nodes.first().focus();
  await page.keyboard.press("b");
  await expect(nodes).toHaveCount(30);
  await expect(page.getByTestId("route-5")).toHaveText(before, { useInnerText: true });
  await expect(field.locator('[data-route-index="5"] polyline').last()).toHaveAttribute("marker-end", /url\(/);
  for (const slot of [5, 6]) await expect(field.locator(`[data-lineup-slot="${slot}"] text`)).toHaveText("WR");
});
