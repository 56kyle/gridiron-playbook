import { expect, test } from "@playwright/test";
import type * as Storage from "../../src/storage";

type StorageHarness = Window & {
  testStorage: typeof Storage;
  workspaceSession?: Storage.WorkspaceSession;
};

test.beforeEach(async ({ page }) => {
  await page.goto("test-harness.html");
  await page.waitForFunction(() => Boolean((window as StorageHarness).testStorage));
});

test("stores opaque documents and rejects stale revisions without overwriting", async ({ page }) => {
  const result = await page.evaluate(async () => {
    const storage = (window as StorageHarness).testStorage;
    const id = crypto.randomUUID();
    const data = '{"metadata":9007199254740993,"point":-0}';
    await storage.writeWorkingCopy(id, 0, data);
    let code = "";
    try {
      await storage.writeWorkingCopy(id, 0, "stale");
    } catch (error) {
      if (error instanceof storage.WorkspaceStorageError) code = error.code;
      else throw error;
    }
    return { copy: await storage.readWorkingCopy(id), code };
  });
  expect(result.copy?.data).toBe('{"metadata":9007199254740993,"point":-0}');
  expect(result.copy?.revision).toBe(1);
  expect(result.code).toBe("conflict");
});

test("queues snapshots in save order", async ({ page }) => {
  const result = await page.evaluate(async () => {
    const session = await (window as StorageHarness).testStorage.openWorkspace();
    await Promise.all([session.save("first"), session.save("second"), session.save("third")]);
    const result = { data: session.data, revision: session.revision, pending: session.pending };
    await session.close();
    return result;
  });
  expect(result).toEqual({ data: "third", revision: 3, pending: 0 });
});

test("independent windows clone working copies and refresh restores the owning copy", async ({ page, context }) => {
  const firstId = await page.evaluate(async () => {
    const harness = window as StorageHarness;
    harness.workspaceSession = await harness.testStorage.openWorkspace();
    await harness.workspaceSession.save("first window");
    return harness.workspaceSession.id;
  });
  const second = await context.newPage();
  await second.goto("test-harness.html");
  await second.waitForFunction(() => Boolean((window as StorageHarness).testStorage));
  const clone = await second.evaluate(async () => {
    const harness = window as StorageHarness;
    harness.workspaceSession = await harness.testStorage.openWorkspace();
    const initial = harness.workspaceSession.data;
    await harness.workspaceSession.save("second window");
    return { id: harness.workspaceSession.id, initial };
  });
  expect(clone.id).not.toBe(firstId);
  expect(clone.initial).toBe("first window");
  await page.bringToFront();
  await page.reload();
  await page.waitForFunction(() => Boolean((window as StorageHarness).testStorage));
  const recovered = await page.evaluate(async () => {
    const session = await (window as StorageHarness).testStorage.openWorkspace();
    const result = { id: session.id, data: session.data };
    await session.close();
    return result;
  });
  expect(recovered).toEqual({ id: firstId, data: "first window" });
});

test("reopening restores the most recently saved workspace", async ({ page, context }) => {
  const original = await page.evaluate(async () => {
    const session = await (window as StorageHarness).testStorage.openWorkspace();
    await session.save("reopen me");
    const id = session.id;
    await session.close();
    return id;
  });
  await page.close();
  const reopened = await context.newPage();
  await reopened.goto("test-harness.html");
  await reopened.waitForFunction(() => Boolean((window as StorageHarness).testStorage));
  const recovered = await reopened.evaluate(async () => {
    const session = await (window as StorageHarness).testStorage.openWorkspace();
    const result = { id: session.id, data: session.data };
    await session.close();
    return result;
  });
  expect(recovered).toEqual({ id: original, data: "reopen me" });
});

test("a stale owner forks its edits and retains the competing save", async ({ page }) => {
  const result = await page.evaluate(async () => {
    const storage = (window as StorageHarness).testStorage;
    const session = await storage.openWorkspace();
    await session.save("initial");
    const originalId = session.id;
    await storage.writeWorkingCopy(originalId, session.revision, "competing writer");
    await session.save("my newer edit");
    const result = {
      originalId,
      newId: session.id,
      original: (await storage.readWorkingCopy(originalId))?.data,
      fork: (await storage.readWorkingCopy(session.id))?.data,
    };
    await session.close();
    return result;
  });
  expect(result.newId).not.toBe(result.originalId);
  expect(result.original).toBe("competing writer");
  expect(result.fork).toBe("my newer edit");
});

test("actual interaction selects the recent workspace and background saves do not replace it", async ({
  page,
  context,
}) => {
  const firstId = await page.evaluate(async () => {
    const harness = window as StorageHarness;
    harness.workspaceSession = await harness.testStorage.openWorkspace();
    const button = document.createElement("button");
    button.textContent = "Use workspace";
    document.body.append(button);
    await harness.workspaceSession.save("first window");
    return harness.workspaceSession.id;
  });
  const second = await context.newPage();
  await second.goto("test-harness.html");
  await second.waitForFunction(() => Boolean((window as StorageHarness).testStorage));
  const secondId = await second.evaluate(async () => {
    const harness = window as StorageHarness;
    harness.workspaceSession = await harness.testStorage.openWorkspace();
    const button = document.createElement("button");
    button.textContent = "Use workspace";
    document.body.append(button);
    await harness.workspaceSession.save("second window");
    return harness.workspaceSession.id;
  });

  await page.bringToFront();
  await page.getByRole("button", { name: "Use workspace" }).click();
  expect(await page.evaluate(() => localStorage.getItem("gridiron.recent-workspace"))).toBe(firstId);

  await second.bringToFront();
  await second.getByRole("button", { name: "Use workspace" }).click();
  expect(await second.evaluate(() => localStorage.getItem("gridiron.recent-workspace"))).toBe(secondId);
  await page.evaluate(async () => {
    await (window as StorageHarness).workspaceSession!.save("background save");
  });
  expect(await second.evaluate(() => localStorage.getItem("gridiron.recent-workspace"))).toBe(secondId);

  await page.bringToFront();
  await page.keyboard.press("Tab");
  expect(await page.evaluate(() => localStorage.getItem("gridiron.recent-workspace"))).toBe(firstId);
  expect(
    await page.evaluate(async () => {
      const harness = window as StorageHarness;
      return (await harness.testStorage.readWorkingCopy(harness.workspaceSession!.id))?.data;
    })
  ).toBe("background save");
});

test("closed workspaces stop claiming activity", async ({ page, context }) => {
  await page.evaluate(async () => {
    const harness = window as StorageHarness;
    harness.workspaceSession = await harness.testStorage.openWorkspace();
    const button = document.createElement("button");
    button.textContent = "Use workspace";
    document.body.append(button);
    await harness.workspaceSession.save("closed window");
  });
  const second = await context.newPage();
  await second.goto("test-harness.html");
  await second.waitForFunction(() => Boolean((window as StorageHarness).testStorage));
  const secondId = await second.evaluate(async () => {
    const harness = window as StorageHarness;
    harness.workspaceSession = await harness.testStorage.openWorkspace();
    await harness.workspaceSession.save("open window");
    return harness.workspaceSession.id;
  });
  await second.keyboard.press("Tab");
  expect(await second.evaluate(() => localStorage.getItem("gridiron.recent-workspace"))).toBe(secondId);
  await page.evaluate(async () => {
    await (window as StorageHarness).workspaceSession!.close();
  });
  await page.bringToFront();
  await page.getByRole("button", { name: "Use workspace" }).click();
  await page.keyboard.press("Tab");
  expect(await page.evaluate(() => localStorage.getItem("gridiron.recent-workspace"))).toBe(secondId);
});

test("corrupt recovery records are reported and retained", async ({ page }) => {
  const result = await page.evaluate(async () => {
    const storage = (window as StorageHarness).testStorage;
    const id = crypto.randomUUID();
    await storage.writeWorkingCopy(id, 0, "original");
    await new Promise<void>((resolve, reject) => {
      const request = indexedDB.open("gridiron-playbook");
      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        const database = request.result;
        const transaction = database.transaction("working-copies", "readwrite");
        transaction.objectStore("working-copies").put({ id, version: 999, data: "original" });
        transaction.oncomplete = () => {
          database.close();
          resolve();
        };
        transaction.onerror = () => {
          database.close();
          reject(transaction.error);
        };
      };
    });
    let code = "";
    try {
      await storage.readWorkingCopy(id);
    } catch (error) {
      if (error instanceof storage.WorkspaceStorageError) code = error.code;
      else throw error;
    }
    return code;
  });
  expect(result).toBe("corrupt");
});
