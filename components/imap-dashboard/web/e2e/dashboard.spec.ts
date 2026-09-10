import os from "node:os";
import path from "node:path";
import { expect, test } from "@playwright/test";

for (const viewport of [
  { name: "side-panel", width: 420, height: 900 },
  { name: "desktop", width: 1280, height: 800 },
]) {
  test(`${viewport.name} production dashboard is usable`, async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error" || message.type() === "warning") errors.push(message.text());
    });
    page.on("pageerror", (error) => errors.push(error.message));
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto("/mail-app.html?standalone=1");

    await expect(page).toHaveTitle("IMAP Dashboard");
    await expect(page.getByRole("heading", { name: "Projectupdate en volgende stappen" })).toBeVisible();
    const brain = page.getByRole("region", { name: "Brein" });
    await expect(brain).toBeVisible();
    const highlights = brain.getByRole("tab", { name: "Highlights" });
    const actions = brain.getByRole("tab", { name: "Acties" });
    await actions.click();
    await expect(actions).toHaveAttribute("aria-selected", "true");
    await highlights.click();
    await expect(highlights).toHaveAttribute("aria-selected", "true");
    await actions.click();
    await expect(brain).toContainText("Planning bevestigen");

    await page.getByRole("button", { name: "Naar prullenbak" }).click();
    await expect(page.getByRole("dialog", { name: "Dit bericht naar de prullenbak verplaatsen?" })).toBeVisible();
    await page.getByRole("button", { name: "Annuleren" }).click();
    await expect(page.getByRole("dialog")).toHaveCount(0);

    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
    expect(errors).toEqual([]);
    await page.screenshot({ path: path.join(os.tmpdir(), `imap-dashboard-${viewport.width}x${viewport.height}.png`) });
  });
}
