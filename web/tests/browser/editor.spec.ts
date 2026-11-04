import { expect, test } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { downloadedBytes, fixtureSave, openBook, playNames, ready, waitForRecovery } from "./helpers";

test("loads the complete editor and Wasm from a GitHub Pages subdirectory", async ({ page }) => {
  const failures: string[] = [];
  const sockets: string[] = [];
  page.on("requestfailed", (request) => failures.push(request.url()));
  page.on("websocket", (socket) => sockets.push(socket.url()));
  await page.goto("./");
  await ready(page);
  await page.getByTestId("open-files").setInputFiles(fixtureSave);
  await expect(page.getByTestId("play-row")).toHaveCount(24);
  await expect(page.getByTestId("play-field").locator("[data-lineup-slot]")).toHaveCount(7);
  await waitForRecovery(page);
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download .sav", exact: true }).click();
  expect(await downloadedBytes(await download)).toEqual(await readFile(fixtureSave));
  expect(failures).toEqual([]);
  expect(sockets).toEqual([]);
  await page.screenshot({ path: ".tools/editor-desktop.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: ".tools/editor-mobile.png", fullPage: true });
});

test("opens imported books as separate tabs and restores the active working copy on refresh", async ({ page }) => {
  await page.goto("./");
  await openBook(page, "First", 4);
  await openBook(page, "Second", 2);
  await expect(page.getByRole("tab")).toHaveCount(2);
  await page.getByRole("tab", { name: "First.sav", exact: true }).click();
  await expect(playNames(page)).toHaveText(["First 1", "First 2", "First 3", "First 4"]);
  await waitForRecovery(page);
  await page.reload();
  await expect(page.getByRole("tab")).toHaveCount(2);
  await expect(page.getByRole("tab", { name: "First.sav", exact: true })).toHaveAttribute("aria-selected", "true");
  await expect(playNames(page)).toHaveText(["First 1", "First 2", "First 3", "First 4"]);
});

test("renaming a play leaves every unrelated save byte unchanged", async ({ page }) => {
  await page.goto("./");
  await ready(page);
  await page.getByTestId("open-files").setInputFiles(fixtureSave);
  await expect(page.getByTestId("play-row")).toHaveCount(24);
  const name = page.getByLabel("Play name", { exact: true });
  await name.fill("S11A-SWRT");
  await name.press("Tab");
  await expect(playNames(page).first()).toHaveText("S11A-SWRT");
  const transfer = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download .sav", exact: true }).click();
  const actual = await downloadedBytes(await transfer);
  const expected = Buffer.from(await readFile(fixtureSave));
  const offset = expected.indexOf(Buffer.from("P11A-SWRT"));
  expect(offset).toBeGreaterThan(0);
  expected[offset] = "S".charCodeAt(0);
  expect(actual).toEqual(expected);
});

test("creates and downloads a new playbook without an imported template", async ({ page }) => {
  await page.goto("./");
  await ready(page);
  await page.getByRole("button", { name: "New playbook", exact: true }).first().click();
  await expect(page.getByRole("tab")).toHaveCount(1);
  await page.getByRole("button", { name: "New play", exact: true }).click();
  const create = page.getByRole("dialog", { name: "New play", exact: true });
  await create.getByLabel("Play name", { exact: true }).fill("First ever");
  await create.getByLabel("Formation", { exact: true }).selectOption("Shotgun Left");
  await create.getByRole("button", { name: "Create play", exact: true }).click();
  await expect(playNames(page)).toHaveText(["First ever"]);
  const transfer = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download .sav", exact: true }).click();
  const bytes = await downloadedBytes(await transfer);
  await page
    .getByTestId("open-files")
    .setInputFiles({ name: "new.sav", mimeType: "application/octet-stream", buffer: bytes });
  await expect(page.getByRole("tab")).toHaveCount(2);
  await expect(playNames(page)).toHaveText(["First ever"]);
  await expect(page.getByLabel("Formation", { exact: true })).toHaveValue("Shotgun Left");
});

test("opening a new browser window creates an independent working copy", async ({ page, context }) => {
  await page.goto("./");
  await openBook(page, "Original", 3);
  await waitForRecovery(page);
  const second = await context.newPage();
  await second.goto("./");
  await expect(playNames(second)).toHaveText(["Original 1", "Original 2", "Original 3"]);
  await openBook(second, "Independent", 1);
  await waitForRecovery(second);
  await page.bringToFront();
  await expect(page.getByRole("tab")).toHaveCount(1);
  await page.reload();
  await expect(page.getByRole("tab")).toHaveCount(1);
  await expect(playNames(page)).toHaveText(["Original 1", "Original 2", "Original 3"]);
  await second.bringToFront();
  await second.getByRole("tab", { name: "Independent.sav", exact: true }).click();
  await waitForRecovery(second);
  const saved = await second.evaluate(async () => {
    const id = sessionStorage.getItem("gridiron.workspace");
    const request = indexedDB.open("gridiron-playbook");
    const database = await new Promise<IDBDatabase>((resolve, reject) => {
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    try {
      const read = database.transaction("working-copies", "readonly").objectStore("working-copies").get(id!);
      const row = await new Promise<{ data: string }>((resolve, reject) => {
        read.onsuccess = () => resolve(read.result as { data: string });
        read.onerror = () => reject(read.error);
      });
      return { id, recent: localStorage.getItem("gridiron.recent-workspace"), data: row.data };
    } finally {
      database.close();
    }
  });
  expect(saved.recent).toBe(saved.id);
  expect(JSON.parse(saved.data)).toMatchObject({ tabs: [{ name: "Original.sav" }, { name: "Independent.sav" }] });
  await page.close();
  await second.close();
  const reopened = await context.newPage();
  await reopened.goto("./");
  await expect(reopened.getByRole("tab")).toHaveCount(2);
  await expect(playNames(reopened)).toHaveText(["Independent 1"]);
});

test("new and duplicated plays are prepended and participate in undo and redo", async ({ page }) => {
  await page.goto("./");
  await openBook(page, "Source", 2);
  await page.getByRole("button", { name: "New play", exact: true }).click();
  const create = page.getByRole("dialog", { name: "New play", exact: true });
  await create.getByLabel("Play name", { exact: true }).fill("Fresh play");
  await create.getByRole("button", { name: "Create play", exact: true }).click();
  await expect(playNames(page)).toHaveText(["Fresh play", "Source 1", "Source 2"]);
  await page.getByRole("button", { name: "Duplicate play", exact: true }).click();
  const duplicate = page.getByRole("dialog", { name: "Duplicate play", exact: true });
  await duplicate.getByLabel("Play name", { exact: true }).fill("Copied play");
  await duplicate.getByRole("button", { name: "Duplicate play", exact: true }).click();
  await expect(playNames(page)).toHaveText(["Copied play", "Fresh play", "Source 1", "Source 2"]);
  await page.getByRole("button", { name: "Undo", exact: true }).click();
  await expect(playNames(page)).toHaveText(["Fresh play", "Source 1", "Source 2"]);
  await page.getByRole("button", { name: "Redo", exact: true }).click();
  await expect(playNames(page)).toHaveText(["Copied play", "Fresh play", "Source 1", "Source 2"]);
  await waitForRecovery(page);
  await page.reload();
  await expect(playNames(page)).toHaveText(["Copied play", "Fresh play", "Source 1", "Source 2"]);
});

for (const mode of ["Copy", "Move"] as const) {
  test(`${mode.toLowerCase()} preserves selected order and undo restores both books`, async ({ page }) => {
    await page.goto("./");
    await openBook(page, "Source", 4);
    await openBook(page, "Destination", 2);
    await page.getByRole("tab", { name: "Source.sav", exact: true }).click();
    await page.getByTestId("play-row").nth(1).click();
    await page.getByRole("checkbox", { name: "Select Source 4", exact: true }).check();
    await page.getByRole("button", { name: `${mode} to…`, exact: true }).click();
    const transfer = page.getByRole("dialog", { name: `${mode} plays`, exact: true });
    await transfer.getByLabel("Destination", { exact: true }).selectOption({ label: "Destination.sav" });
    await transfer.getByRole("button", { name: `${mode} plays`, exact: true }).click();
    await page.getByRole("tab", { name: "Destination.sav", exact: true }).click();
    await expect(playNames(page)).toHaveText(["Source 2", "Source 4", "Destination 1", "Destination 2"]);
    await page.getByRole("tab", { name: "Source.sav", exact: true }).click();
    await expect(playNames(page)).toHaveText(
      mode === "Move" ? ["Source 1", "Source 3"] : ["Source 1", "Source 2", "Source 3", "Source 4"]
    );
    await page.getByRole("button", { name: "Undo", exact: true }).click();
    await page.getByRole("tab", { name: "Source.sav", exact: true }).click();
    await expect(playNames(page)).toHaveText(["Source 1", "Source 2", "Source 3", "Source 4"]);
    await page.getByRole("tab", { name: "Destination.sav", exact: true }).click();
    await expect(playNames(page)).toHaveText(["Destination 1", "Destination 2"]);
  });
}

test("reordering and merging retain the source order", async ({ page }) => {
  await page.goto("./");
  await openBook(page, "Source", 3);
  await page.getByTestId("play-row").nth(2).click();
  await page.getByRole("button", { name: "Move up", exact: true }).click();
  await expect(playNames(page)).toHaveText(["Source 1", "Source 3", "Source 2"]);
  await openBook(page, "Destination", 1);
  await page.getByRole("tab", { name: "Source.sav", exact: true }).click();
  await page.getByRole("button", { name: "Merge into…", exact: true }).click();
  const merge = page.getByRole("dialog", { name: "Merge playbook", exact: true });
  await merge.getByLabel("Destination", { exact: true }).selectOption({ label: "Destination.sav" });
  await merge.getByRole("button", { name: "Merge playbook", exact: true }).click();
  await page.getByRole("tab", { name: "Destination.sav", exact: true }).click();
  await expect(playNames(page)).toHaveText(["Source 1", "Source 3", "Source 2", "Destination 1"]);
});

for (const malformed of ["truncated", "unpaired UTF16"] as const) {
  test(`recovers from a ${malformed} save and subsequently imports a valid one`, async ({ page }) => {
    await page.goto("./");
    await ready(page);
    const source = await readFile(fixtureSave);
    const bytes =
      malformed === "truncated"
        ? Buffer.from("GVAS\0\0")
        : Buffer.concat([source.subarray(0, 26), Buffer.from("ffffffff00d8", "hex")]);
    await page.getByTestId("open-files").setInputFiles({
      name: "invalid.sav",
      mimeType: "application/octet-stream",
      buffer: bytes,
    });
    await expect(page.getByRole("alert")).toBeVisible();
    await expect(page.getByRole("tab")).toHaveCount(0);
    await page.getByTestId("open-files").setInputFiles(fixtureSave);
    await expect(page.getByTestId("play-row")).toHaveCount(24);
  });
}
