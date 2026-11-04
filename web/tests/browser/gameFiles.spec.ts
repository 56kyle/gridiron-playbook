import { expect, test } from "@playwright/test";
import type * as GameFiles from "../../src/gameFiles";

type GameHarness = Window & { testGameFiles: typeof GameFiles };

test.beforeEach(async ({ page }) => {
  await page.goto("test-harness.html");
  await page.waitForFunction(() => Boolean((window as GameHarness).testGameFiles));
});

test("preparation is read-only and installation preserves the original bytes", async ({ page }) => {
  const result = await page.evaluate(async () => {
    const api = (window as GameHarness).testGameFiles;
    const root = await navigator.storage.getDirectory();
    const directory = await root.getDirectoryHandle(crypto.randomUUID(), { create: true });
    const target = await directory.getFileHandle(api.GAME_SAVE_NAME, { create: true });
    const original = new Uint8Array([0, 255, 10, 222]);
    let stream = await target.createWritable();
    await stream.write(original);
    await stream.close();
    const next = new Uint8Array([1, 2, 3, 4]);
    const prepared = await api.prepareInstall(directory, next);
    next[0] = 99;
    const before = Array.from(new Uint8Array(await (await target.getFile()).arrayBuffer()));
    const namesBefore: string[] = [];
    for await (const [name] of directory.entries()) namesBefore.push(name);
    const changed = await prepared.apply();
    if (!changed.backupName) throw new Error("Expected a backup.");
    const archive = await directory.getDirectoryHandle(api.GAME_BACKUP_DIRECTORY);
    const backup = await archive.getFileHandle(changed.backupName.split("/")[1]!);
    const backupBytes = Array.from(new Uint8Array(await (await backup.getFile()).arrayBuffer()));
    const installed = Array.from(new Uint8Array(await (await target.getFile()).arrayBuffer()));
    return { before, namesBefore, changed: changed.changed, backupBytes, installed };
  });
  expect(result.before).toEqual([0, 255, 10, 222]);
  expect(result.namesBefore).toEqual(["GridironCustomPlays.sav"]);
  expect(result.backupBytes).toEqual(result.before);
  expect(result.installed).toEqual([1, 2, 3, 4]);
  expect(result.changed).toBe(true);
});

test("repeated restore swaps playbooks while retaining every replaced version", async ({ page }) => {
  const result = await page.evaluate(async () => {
    const api = (window as GameHarness).testGameFiles;
    const directory = await (
      await navigator.storage.getDirectory()
    ).getDirectoryHandle(crypto.randomUUID(), {
      create: true,
    });
    const target = await directory.getFileHandle(api.GAME_SAVE_NAME, { create: true });
    const stream = await target.createWritable();
    await stream.write("original");
    await stream.close();
    await (await api.prepareInstall(directory, new TextEncoder().encode("replacement"))).apply();
    const restoration = await api.prepareRestore(directory);
    const firstRestore = await restoration.apply();
    const restored = await (await target.getFile()).text();
    await (await api.prepareRestore(directory)).apply();
    const secondRestore = await (await target.getFile()).text();
    const archive = await directory.getDirectoryHandle(api.GAME_BACKUP_DIRECTORY);
    const backups: string[] = [];
    for await (const [name, handle] of archive.entries()) {
      if (handle.kind === "file" && name.endsWith(".sav")) backups.push(await (await handle.getFile()).text());
    }
    return {
      restored,
      secondRestore,
      backups: backups.sort(),
      restoreSource: restoration.restoreBackupName,
      savedPrevious: firstRestore.backupName,
    };
  });
  expect(result.restored).toBe("original");
  expect(result.secondRestore).toBe("replacement");
  expect(result.backups).toEqual(["original", "original", "replacement"]);
  expect(result.restoreSource).not.toBe(result.savedPrevious);
});

test("stale confirmation cannot replace a changed game save", async ({ page }) => {
  const result = await page.evaluate(async () => {
    const api = (window as GameHarness).testGameFiles;
    const directory = await (
      await navigator.storage.getDirectory()
    ).getDirectoryHandle(crypto.randomUUID(), {
      create: true,
    });
    const target = await directory.getFileHandle(api.GAME_SAVE_NAME, { create: true });
    let stream = await target.createWritable();
    await stream.write("original");
    await stream.close();
    const prepared = await api.prepareInstall(directory, new TextEncoder().encode("replacement"));
    stream = await target.createWritable();
    await stream.write("game changed this");
    await stream.close();
    let code = "";
    try {
      await prepared.apply();
    } catch (error) {
      if (error instanceof api.GameFileError) code = error.code;
      else throw error;
    }
    return { code, current: await (await target.getFile()).text() };
  });
  expect(result).toEqual({ code: "changed", current: "game changed this" });
});

test("identical installation creates no backup files", async ({ page }) => {
  const result = await page.evaluate(async () => {
    const api = (window as GameHarness).testGameFiles;
    const directory = await (
      await navigator.storage.getDirectory()
    ).getDirectoryHandle(crypto.randomUUID(), {
      create: true,
    });
    const target = await directory.getFileHandle(api.GAME_SAVE_NAME, { create: true });
    const stream = await target.createWritable();
    await stream.write("same");
    await stream.close();
    const change = await (await api.prepareInstall(directory, new TextEncoder().encode("same"))).apply();
    const names: string[] = [];
    for await (const [name] of directory.entries()) names.push(name);
    return { change, names };
  });
  expect(result.change.changed).toBe(false);
  expect(result.change.backupName).toBeNull();
  expect(result.names).toEqual(["GridironCustomPlays.sav"]);
});

test("an unusable backup folder blocks installation", async ({ page }) => {
  const result = await page.evaluate(async () => {
    const api = (window as GameHarness).testGameFiles;
    const directory = await (
      await navigator.storage.getDirectory()
    ).getDirectoryHandle(crypto.randomUUID(), {
      create: true,
    });
    const target = await directory.getFileHandle(api.GAME_SAVE_NAME, { create: true });
    const stream = await target.createWritable();
    await stream.write("original");
    await stream.close();
    await directory.getFileHandle(api.GAME_BACKUP_DIRECTORY, { create: true });
    const prepared = await api.prepareInstall(directory, new TextEncoder().encode("replacement"));
    let code = "";
    try {
      await prepared.apply();
    } catch (error) {
      if (error instanceof api.GameFileError) code = error.code;
      else throw error;
    }
    return { code, current: await (await target.getFile()).text() };
  });
  expect(result).toEqual({ code: "backup-write", current: "original" });
});

test("corrupt latest backup is reported without falling back to an older version", async ({ page }) => {
  const result = await page.evaluate(async () => {
    const api = (window as GameHarness).testGameFiles;
    const directory = await (
      await navigator.storage.getDirectory()
    ).getDirectoryHandle(crypto.randomUUID(), {
      create: true,
    });
    const target = await directory.getFileHandle(api.GAME_SAVE_NAME, { create: true });
    let stream = await target.createWritable();
    await stream.write("original");
    await stream.close();
    await (await api.prepareInstall(directory, new TextEncoder().encode("second"))).apply();
    const latest = await (await api.prepareInstall(directory, new TextEncoder().encode("third"))).apply();
    const archive = await directory.getDirectoryHandle(api.GAME_BACKUP_DIRECTORY);
    const backup = await archive.getFileHandle(latest.backupName!.split("/")[1]!);
    stream = await backup.createWritable();
    await stream.write("corrupt");
    await stream.close();
    let code = "";
    try {
      await api.prepareRestore(directory);
    } catch (error) {
      if (error instanceof api.GameFileError) code = error.code;
      else throw error;
    }
    return { code, current: await (await target.getFile()).text() };
  });
  expect(result).toEqual({ code: "corrupt-backup", current: "third" });
});

test("another application writer prevents installation", async ({ page }) => {
  const result = await page.evaluate(async () => {
    const api = (window as GameHarness).testGameFiles;
    const directory = await (
      await navigator.storage.getDirectory()
    ).getDirectoryHandle(crypto.randomUUID(), {
      create: true,
    });
    const target = await directory.getFileHandle(api.GAME_SAVE_NAME, { create: true });
    const stream = await target.createWritable();
    await stream.write("original");
    await stream.close();
    const prepared = await api.prepareInstall(directory, new TextEncoder().encode("replacement"));
    let code = "";
    await navigator.locks.request("gridiron.game-save-write", async () => {
      try {
        await prepared.apply();
      } catch (error) {
        if (error instanceof api.GameFileError) code = error.code;
        else throw error;
      }
    });
    return { code, current: await (await target.getFile()).text() };
  });
  expect(result).toEqual({ code: "busy", current: "original" });
});

test("a locked replacement retains a verified backup and reports its location", async ({ page }) => {
  const result = await page.evaluate(async () => {
    const api = (window as GameHarness).testGameFiles;
    const directory = await (
      await navigator.storage.getDirectory()
    ).getDirectoryHandle(crypto.randomUUID(), {
      create: true,
    });
    const target = await directory.getFileHandle(api.GAME_SAVE_NAME, { create: true });
    const initial = await target.createWritable();
    await initial.write("original");
    await initial.close();
    const prepared = await api.prepareInstall(directory, new TextEncoder().encode("replacement"));
    const options = { keepExistingData: true, mode: "exclusive" };
    const heldWriter = await target.createWritable(options);
    let code = "";
    let backupName: string | null = null;
    try {
      await prepared.apply();
    } catch (error) {
      if (error instanceof api.GameFileError) {
        code = error.code;
        backupName = error.backupName;
      } else throw error;
    } finally {
      await heldWriter.abort();
    }
    const archive = await directory.getDirectoryHandle(api.GAME_BACKUP_DIRECTORY);
    const backup = backupName ? await archive.getFileHandle(backupName.split("/")[1]!) : null;
    return {
      code,
      backupName,
      backup: backup ? await (await backup.getFile()).text() : null,
      current: await (await target.getFile()).text(),
    };
  });
  expect(result.code).toBe("replacement");
  expect(result.backupName).toContain("GridironPlaybookBackups/");
  expect(result.backup).toBe("original");
  expect(result.current).toBe("original");
});
