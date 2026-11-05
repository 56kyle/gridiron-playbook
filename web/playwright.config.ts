import { defineConfig } from "@playwright/test";
import { fileURLToPath } from "node:url";

const repository = fileURLToPath(new URL("../", import.meta.url));

export default defineConfig({
  testDir: "./tests/browser",
  forbidOnly: Boolean(process.env.CI),
  timeout: 60_000,
  expect: { timeout: 12_000 },
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  outputDir: "../test-results",
  use: {
    baseURL: "http://127.0.0.1:4173/gridiron-playbook/",
    channel: process.env.PLAYWRIGHT_CHANNEL ?? (process.platform === "win32" ? "msedge" : undefined),
    viewport: { width: 1440, height: 1000 },
    acceptDownloads: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "node web/tests/browser/serve-static.mjs",
    cwd: repository,
    url: "http://127.0.0.1:4173/gridiron-playbook/",
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
