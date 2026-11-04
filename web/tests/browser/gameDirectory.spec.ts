import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { DEFAULT_WINDOWS_STEAM_FOLDER } from "../../src/gameDirectory";
import { openBook, ready } from "./helpers";

interface PickerState {
  picks: number;
  permission: PermissionState;
  nextPermission: PermissionState;
  requests: { active: boolean; mode: string }[];
  result: "valid" | "cancel" | "missing";
  startIn: string | null;
}
declare global {
  interface Window {
    folderPicker: PickerState;
  }
}

async function installPicker(page: Page, permission: PermissionState = "granted"): Promise<void> {
  await page.addInitScript((initialPermission) => {
    const state: PickerState = {
      picks: 0,
      permission: initialPermission,
      nextPermission: "granted",
      requests: [],
      result: "valid",
      startIn: null,
    };
    window.folderPicker = state;
    Object.defineProperty(FileSystemDirectoryHandle.prototype, "queryPermission", {
      configurable: true,
      value: async () => state.permission,
    });
    Object.defineProperty(FileSystemDirectoryHandle.prototype, "requestPermission", {
      configurable: true,
      value: async (options: { mode: string }) => {
        state.requests.push({ active: navigator.userActivation.isActive, mode: options.mode });
        state.permission = state.nextPermission;
        return state.permission;
      },
    });
    Object.defineProperty(window, "showDirectoryPicker", {
      configurable: true,
      value: async (options: { startIn?: FileSystemDirectoryHandle }) => {
        state.picks++;
        state.startIn = options.startIn?.name ?? null;
        if (state.result === "cancel") throw new DOMException("Cancelled", "AbortError");
        const root = await navigator.storage.getDirectory();
        if (state.result === "missing") return root.getDirectoryHandle("wrong-folder", { create: true });
        const installation = await root.getDirectoryHandle("Gridiron installation", { create: true });
        const game = await installation.getDirectoryHandle("Gridiron", { create: true });
        const saved = await game.getDirectoryHandle("Saved", { create: true });
        const saves = await saved.getDirectoryHandle("SaveGames", { create: true });
        try {
          await saves.getFileHandle("GridironCustomPlays.sav");
        } catch {
          const file = await saves.getFileHandle("GridironCustomPlays.sav", { create: true });
          const stream = await file.createWritable();
          await stream.write("original game save");
          await stream.close();
        }
        state.permission = "granted";
        return installation;
      },
    });
  }, permission);
}

async function gameMenu(page: Page, action: string): Promise<void> {
  const menu = page.locator(".game-menu");
  if ((await menu.getAttribute("open")) === null) await menu.locator("summary").click();
  await menu.getByRole("button", { name: action, exact: true }).click();
}

async function chooseInitialFolder(page: Page): Promise<void> {
  await page.goto("./");
  await ready(page);
  await gameMenu(page, "Game folder…");
  await page.getByRole("button", { name: "Choose folder…", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Game folder", exact: true })).toHaveCount(0);
  await expect(page.getByRole("status").filter({ hasText: "Game folder connected" })).toBeVisible();
}

async function savedBytes(page: Page): Promise<string> {
  return page.evaluate(async () => {
    let directory = await navigator.storage.getDirectory();
    for (const segment of ["Gridiron installation", "Gridiron", "Saved", "SaveGames"]) {
      directory = await directory.getDirectoryHandle(segment);
    }
    return (await (await directory.getFileHandle("GridironCustomPlays.sav")).getFile()).text();
  });
}

test("first selection offers a path hint and accepts the install folder without changing the save", async ({
  page,
  context,
}) => {
  await installPicker(page);
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("./");
  await openBook(page);
  await gameMenu(page, "Use in game");
  const dialog = page.getByRole("dialog", { name: "Game folder", exact: true });
  await expect(dialog).toBeVisible();
  if (await page.evaluate(() => navigator.userAgent.includes("Windows"))) {
    await expect(page.getByLabel("Default Steam folder")).toHaveValue(DEFAULT_WINDOWS_STEAM_FOLDER);
    await dialog.getByRole("button", { name: "Copy path", exact: true }).click();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(DEFAULT_WINDOWS_STEAM_FOLDER);
  }
  await page.screenshot({ path: ".tools/game-folder-first.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: ".tools/game-folder-mobile.png", fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await dialog.getByRole("button", { name: "Choose folder…", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Use in game", exact: true })).toBeVisible();
  expect(await savedBytes(page)).toBe("original game save");
  await page.reload();
  await ready(page);
  await gameMenu(page, "Use in game");
  await expect(page.getByRole("dialog", { name: "Use in game", exact: true })).toBeVisible();
  expect(await page.evaluate(() => window.folderPicker.picks)).toBe(0);
  expect(await savedBytes(page)).toBe("original game save");
});

test("reconnection requests permission only on a click and supports retry after denial", async ({ page }) => {
  await installPicker(page, "prompt");
  await chooseInitialFolder(page);
  await page.reload();
  await openBook(page);
  expect(await page.evaluate(() => window.folderPicker.requests)).toEqual([]);
  await gameMenu(page, "Use in game");
  const dialog = page.getByRole("dialog", { name: "Game folder", exact: true });
  await expect(dialog).toBeVisible();
  expect(await page.evaluate(() => window.folderPicker.requests)).toEqual([]);
  await page.evaluate(() => {
    window.folderPicker.nextPermission = "denied";
  });
  await dialog.getByRole("button", { name: "Use saved folder" }).click();
  await expect(dialog.getByRole("alert")).toContainText("Allow folder access");
  expect(await savedBytes(page)).toBe("original game save");
  await page.evaluate(() => {
    window.folderPicker.nextPermission = "granted";
  });
  await dialog.getByRole("button", { name: "Use saved folder" }).click();
  await expect(page.getByRole("dialog", { name: "Use in game", exact: true })).toBeVisible();
  expect(await page.evaluate(() => window.folderPicker.requests)).toEqual([
    { active: true, mode: "readwrite" },
    { active: true, mode: "readwrite" },
  ]);
});

test("reconnection normalizes rejected permission requests and preserves their cause", async ({ page }) => {
  await page.goto("test-harness.html");
  await page.waitForFunction(() => Boolean(window.testGameDirectory));
  const result = await page.evaluate(async () => {
    const directory = await navigator.storage.getDirectory();
    const failure = new DOMException("Permission request failed", "SecurityError");
    directory.requestPermission = async () => {
      throw failure;
    };
    try {
      await window.testGameDirectory.reconnectGameDirectory(directory);
      return null;
    } catch (cause) {
      if (!(cause instanceof window.testGameFiles.GameFileError)) return null;
      return { code: cause.code, preservesCause: cause.cause === failure };
    }
  });
  expect(result).toEqual({ code: "unavailable", preservesCause: true });
});

test("invalid and cancelled replacements preserve the saved directory and seed the picker", async ({ page }) => {
  await installPicker(page);
  await chooseInitialFolder(page);
  await gameMenu(page, "Game folder…");
  const dialog = page.getByRole("dialog", { name: "Game folder", exact: true });
  await page.evaluate(() => {
    window.folderPicker.result = "missing";
  });
  await dialog.getByRole("button", { name: "Choose another…" }).click();
  await expect(dialog.getByRole("alert")).toContainText("GridironCustomPlays.sav");
  expect(await page.evaluate(() => window.folderPicker.startIn)).toBe("SaveGames");
  await page.evaluate(() => {
    window.folderPicker.result = "cancel";
  });
  await dialog.getByRole("button", { name: "Choose another…" }).click();
  await expect(dialog.getByRole("alert")).toHaveCount(0);
  await page.reload();
  await openBook(page);
  await gameMenu(page, "Use in game");
  await expect(page.getByRole("dialog", { name: "Use in game", exact: true })).toBeVisible();
  expect(await page.evaluate(() => window.folderPicker.picks)).toBe(0);
});

test("forgetting a folder removes only the remembered choice", async ({ page }) => {
  await installPicker(page);
  await chooseInitialFolder(page);
  await gameMenu(page, "Game folder…");
  const dialog = page.getByRole("dialog", { name: "Game folder", exact: true });
  await dialog.getByRole("button", { name: "Forget folder" }).click();
  await expect(dialog.getByRole("button", { name: "Choose folder…", exact: true })).toBeVisible();
  expect(await savedBytes(page)).toBe("original game save");
  await page.reload();
  await openBook(page);
  await gameMenu(page, "Use in game");
  await expect(page.getByRole("dialog", { name: "Game folder", exact: true })).toBeVisible();
});

test("a moved or deleted save opens folder recovery without choosing a different file", async ({ page }) => {
  await installPicker(page);
  await chooseInitialFolder(page);
  await page.evaluate(async () => {
    let directory = await navigator.storage.getDirectory();
    for (const segment of ["Gridiron installation", "Gridiron", "Saved", "SaveGames"]) {
      directory = await directory.getDirectoryHandle(segment);
    }
    await directory.removeEntry("GridironCustomPlays.sav");
  });
  await openBook(page);
  await gameMenu(page, "Use in game");
  const dialog = page.getByRole("dialog", { name: "Game folder", exact: true });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("alert")).toContainText("Could not read");
  expect(await page.evaluate(() => window.folderPicker.picks)).toBe(1);
});

test("blocked preference storage still allows an explicitly selected folder for this visit", async ({ page }) => {
  await installPicker(page);
  await page.addInitScript(() => {
    const open = indexedDB.open.bind(indexedDB);
    indexedDB.open = (name, version) => {
      if (name === "gridiron-game-directory") throw new DOMException("Blocked", "SecurityError");
      return open(name, version);
    };
  });
  await page.goto("./");
  await openBook(page);
  await gameMenu(page, "Use in game");
  await page.getByRole("button", { name: "Choose folder…", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Use in game", exact: true })).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "connected for this visit" })).toBeVisible();
  expect(await savedBytes(page)).toBe("original game save");
});

test("directory handles survive IndexedDB cloning and corrupt records remain recoverable", async ({ page }) => {
  await page.goto("test-harness.html");
  await page.waitForFunction(() => Boolean(window.testGameDirectory));
  const result = await page.evaluate(async () => {
    const api = window.testGameDirectory;
    const root = await navigator.storage.getDirectory();
    await api.rememberGameDirectory(root);
    const restored = await api.readSavedGameDirectory();
    const same = restored && (await root.isSameEntry(restored));
    await api.forgetGameDirectory();
    const forgotten = await api.readSavedGameDirectory();
    await new Promise<void>((resolve, reject) => {
      const request = indexedDB.open("gridiron-game-directory", 1);
      request.onsuccess = () => {
        const database = request.result;
        const transaction = database.transaction("directories", "readwrite");
        transaction.objectStore("directories").put({ kind: "directory", name: "fake" }, "current");
        transaction.oncomplete = () => {
          database.close();
          resolve();
        };
        transaction.onerror = () => {
          database.close();
          reject(transaction.error);
        };
      };
      request.onerror = () => reject(request.error);
    });
    let error = "";
    try {
      await api.readSavedGameDirectory();
    } catch (cause) {
      error = (cause as { code: string }).code;
    }
    await api.rememberGameDirectory(root);
    return { same, forgotten, error, recovered: (await api.readSavedGameDirectory())?.name === root.name };
  });
  expect(result).toEqual({ same: true, forgotten: null, error: "storage", recovered: true });
});
