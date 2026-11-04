import { expect } from "@playwright/test";
import type { Download, Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

export const fixtureSave = fileURLToPath(new URL("../../../data/GridIronCustomPlays.sav", import.meta.url));
const fixtureJson = fileURLToPath(new URL("../../../data/GridIronCustomPlays.json", import.meta.url));

interface FixturePlay {
  FormationName_0: string;
  PlayName_0: string;
  Routes_0: unknown[];
}

interface FixtureDocument {
  root: {
    properties: { CustomPlays_0: FixturePlay[]; [key: string]: unknown };
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export async function bookFile(prefix: string, count = 4) {
  const document = JSON.parse(await readFile(fixtureJson, "utf8")) as FixtureDocument;
  const original = document.root.properties.CustomPlays_0;
  document.root.properties.CustomPlays_0 = Array.from({ length: count }, (_, index) => ({
    ...structuredClone(original[index % original.length]!),
    PlayName_0: `${prefix} ${index + 1}`,
  }));
  return { name: `${prefix}.json`, mimeType: "application/json", buffer: Buffer.from(JSON.stringify(document)) };
}

export async function denseBookFile(points: number) {
  const file = await bookFile("Dense", 1);
  const document = JSON.parse(file.buffer.toString("utf8")) as FixtureDocument;
  document.root.properties.CustomPlays_0[0]!.Routes_0 = [
    {
      Slot_0: 5,
      Points_0: Array.from({ length: points }, (_, index) => ({
        X_0: Math.sin(index * 12.9898) * 4000 + index * 13,
        Y_0: Math.cos(index * 5.123) * 2000,
        Z_0: 0,
      })),
    },
  ];
  return { ...file, buffer: Buffer.from(JSON.stringify(document)) };
}

export async function openBook(page: Page, prefix = "Source", count = 4): Promise<void> {
  await ready(page);
  await page.getByTestId("open-files").setInputFiles(await bookFile(prefix, count));
  await expect(page.getByTestId("play-row")).toHaveCount(count);
}

export async function ready(page: Page): Promise<void> {
  await expect(page.getByRole("button", { name: "Open files", exact: true }).first()).toBeEnabled();
}

export async function waitForRecovery(page: Page): Promise<void> {
  await expect(page.getByTestId("recovery-status")).toHaveText("Saved locally");
}

export function playNames(page: Page) {
  return page.getByTestId("play-row").locator('[data-testid="play-name"]');
}

export async function downloadedBytes(download: Download): Promise<Buffer> {
  const path = await download.path();
  if (!path) throw new Error("The browser did not persist its download.");
  return readFile(path);
}

export async function clickSvg(page: Page, x: number, y: number): Promise<void> {
  const point = await screenPoint(page, x, y);
  await page.mouse.click(point.x, point.y);
}

export async function hoverSvg(page: Page, x: number, y: number): Promise<void> {
  const point = await screenPoint(page, x, y);
  await page.mouse.move(point.x, point.y);
}

async function screenPoint(page: Page, x: number, y: number): Promise<{ x: number; y: number }> {
  const field = page.getByTestId("play-field");
  return field.evaluate(
    (element, coords) => {
      const matrix = (element as SVGSVGElement).getScreenCTM();
      if (!matrix) throw new Error("Field has no screen transform.");
      const screen = new DOMPoint(coords.x, coords.y).matrixTransform(matrix);
      return { x: screen.x, y: screen.y };
    },
    { x, y }
  );
}
