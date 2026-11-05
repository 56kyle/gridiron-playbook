import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { denseBookFile, downloadedBytes, openBook, playNames, ready } from "./helpers";

const legacyBlock =
  "eNpzDwxmZGDkDinPzCtWCMpMzyhhZODySU1PTK5USEosAsrJasb0H_p6ov4AAypo8HhYJbJubeOB1teBO-RUEw_g" +
  "EHeAiYusc39YlUhQHG4OyBh3UYLicHNAxoicbCAkDjenGmRxDUFxBxR_GRAUh5sDCzcC4nBzDn_ViOk3ICgONwdk" +
  "jMaMOkLicHO-AY059L-WkDjcHJAxMekExR1Q_HWuhpD4ARR_mREUdyAUbrjSJwD70_iX";

async function linkFromDialog(page: Page): Promise<string> {
  await expect(page.getByRole("button", { name: "Copy link", exact: true })).toBeEnabled();
  const link = await page.getByLabel("Share link", { exact: true }).inputValue();
  expect(link).toMatch(/^http:\/\/127\.0\.0\.1:4173\/gridiron-playbook\/#v1\//);
  await expect(page.getByTestId("share-length")).toHaveText(`${link.length.toLocaleString()} characters`);
  return link;
}

for (const precision of ["Exact", "1 mm", "1 cm"]) {
  test(`shares an individual play at ${precision} through both link and file`, async ({ page, context }) => {
    await page.goto("./");
    await openBook(page, "Source", 2);
    await page.getByRole("button", { name: "Share play", exact: true }).click();
    await page.getByRole("radio", { name: precision, exact: true }).check();
    const link = await linkFromDialog(page);
    const transfer = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download share file", exact: true }).click();
    const file = await transfer;
    const bytes = await downloadedBytes(file);
    expect(file.suggestedFilename()).toMatch(/\.gridironshare$/);
    expect(Buffer.from(link.split("#v1/")[1]!, "base64url")).toEqual(bytes);

    const recipient = await context.newPage();
    await recipient.goto(link);
    const preview = recipient.getByRole("dialog", { name: "Quickshare", exact: true });
    await expect(preview).toBeVisible();
    const existingPlays = await playNames(recipient).allTextContents();
    await preview.getByRole("button", { name: "Import play", exact: true }).click();
    await expect(preview).toHaveCount(0);
    await expect(playNames(recipient)).toHaveText(["Source 1", ...existingPlays]);
    await ready(recipient);
    await recipient
      .getByTestId("open-files")
      .setInputFiles({ name: "single.gridironshare", mimeType: "application/octet-stream", buffer: bytes });
    await preview.getByRole("button", { name: "Import play", exact: true }).click();
    await expect(preview).toHaveCount(0);
    await expect(playNames(recipient)).toHaveText(["Source 1", "Source 1", ...existingPlays]);
    await recipient.close();
  });
}

test("a 125-play Quickshare file opens as a complete new playbook", async ({ page, context }) => {
  await page.goto("./");
  await openBook(page, "Large", 125);
  await page.getByRole("button", { name: "Share playbook", exact: true }).click();
  const exactLink = await linkFromDialog(page);
  expect(exactLink.length).toBeGreaterThan(4000);
  await page.getByRole("button", { name: "Copy link", exact: true }).click();
  const warning = page.getByRole("dialog", { name: "Exceeds Discord Nitro limit", exact: true });
  await expect(warning).toBeVisible();
  await expect(warning.getByRole("alert")).toContainText("4,000-character Nitro");
  await warning.getByRole("button", { name: "Cancel", exact: true }).click();
  await page.getByRole("radio", { name: "1 cm", exact: true }).check();
  const compactLink = await linkFromDialog(page);
  expect(compactLink.length).toBeLessThan(exactLink.length);
  const compactDownload = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download share file", exact: true }).click();
  const compact = await downloadedBytes(await compactDownload);
  expect(Buffer.from(compactLink.split("#v1/")[1]!, "base64url")).toEqual(compact);
  const exactDownload = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download exact file", exact: true }).click();
  expect(Buffer.from(exactLink.split("#v1/")[1]!, "base64url")).toEqual(await downloadedBytes(await exactDownload));

  const recipient = await context.newPage();
  await recipient.goto("./");
  await openBook(recipient, "Recipient", 1);
  const existing = await recipient.getByRole("tab").count();
  await recipient
    .getByTestId("open-files")
    .setInputFiles({ name: "large.gridironshare", mimeType: "application/octet-stream", buffer: compact });
  await recipient.getByRole("button", { name: "Open playbook", exact: true }).click();
  await expect(recipient.getByRole("tab")).toHaveCount(existing + 1);
  await expect(recipient.getByTestId("play-row")).toHaveCount(125);
  await expect(playNames(recipient).first()).toHaveText("Large 1");
  await expect(playNames(recipient).last()).toHaveText("Large 125");
});

test("copying a non-Nitro-length link requires confirmation and remains possible", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.goto("./");
  await ready(page);
  await page.getByTestId("open-files").setInputFiles(await denseBookFile(140));
  await expect(page.getByTestId("play-row")).toHaveCount(1);
  await page.getByRole("button", { name: "Share play", exact: true }).click();
  const link = await linkFromDialog(page);
  expect(link.length).toBeGreaterThan(2000);
  expect(link.length).toBeLessThanOrEqual(4000);
  await page.getByRole("button", { name: "Copy link", exact: true }).click();
  const warning = page.getByRole("dialog", { name: "Exceeds Discord message limit", exact: true });
  await expect(warning.getByRole("alert")).toContainText("2,000-character non-Nitro");
  await warning.getByRole("button", { name: "Copy anyway", exact: true }).click();
  await expect(warning).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe(link);
});

test("published version-one block links still preview and import", async ({ page }) => {
  await page.goto(`./#v1/${legacyBlock}`);
  await page.getByRole("button", { name: "Import play", exact: true }).click();
  await expect(playNames(page)).toHaveText(["Legacy bar"]);
  await expect(page.getByTestId("route-0")).toContainText("1.0 yds");
});

test("selecting several share files previews and imports every file", async ({ page }) => {
  await page.goto("./");
  await openBook(page, "Source", 1);
  await page.getByRole("button", { name: "Share play", exact: true }).click();
  const link = await linkFromDialog(page);
  const bytes = Buffer.from(link.split("#v1/")[1]!, "base64url");
  await page
    .getByRole("dialog", { name: "Share play", exact: true })
    .getByRole("button", { name: "Close dialog", exact: true })
    .click();
  await page.getByTestId("open-files").setInputFiles([
    { name: "first.gridironshare", mimeType: "application/octet-stream", buffer: bytes },
    { name: "second.gridironshare", mimeType: "application/octet-stream", buffer: bytes },
  ]);
  await page.getByRole("button", { name: "Import play", exact: true }).evaluate((button) => {
    (button as HTMLButtonElement).click();
    button.closest("dialog")!.dispatchEvent(new Event("cancel", { cancelable: true }));
  });
  await expect(page.getByTestId("play-row")).toHaveCount(2);
  await expect(page.getByRole("dialog", { name: "Quickshare", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Import play", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Quickshare", exact: true })).toHaveCount(0);
  await expect(playNames(page)).toHaveText(["Source 1", "Source 1", "Source 1"]);
});
