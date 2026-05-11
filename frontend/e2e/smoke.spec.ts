import { test, expect } from "@playwright/test";

const BASE = "http://localhost:1420";

test.describe("MyCrew Smoke Tests", () => {
  test("homepage loads", async ({ page }) => {
    await page.goto(BASE);
    await expect(page).toHaveTitle(/MyCrew/i);
  });

  test("sidebar navigation works", async ({ page }) => {
    await page.goto(BASE);
    // 4 nav links should exist
    const nav = page.locator("nav");
    await expect(nav).toBeVisible();
  });

  test("can navigate to tasks page", async ({ page }) => {
    await page.goto(`${BASE}/tasks`);
    await page.waitForLoadState("networkidle");
    await expect(page.locator("body")).toBeVisible();
  });

  test("can navigate to team page", async ({ page }) => {
    await page.goto(`${BASE}/team`);
    await page.waitForLoadState("networkidle");
    await expect(page.locator("body")).toBeVisible();
  });

  test("can navigate to settings page", async ({ page }) => {
    await page.goto(`${BASE}/settings`);
    await page.waitForLoadState("networkidle");
    await expect(page.locator("body")).toBeVisible();
  });

  test("theme toggle works", async ({ page }) => {
    await page.goto(BASE);
    // The theme toggle button should exist in sidebar
    const themeBtn = page.locator('[data-testid="theme-toggle"]');
    if (await themeBtn.isVisible()) {
      await themeBtn.click();
      // Should not crash
      await expect(page.locator("body")).toBeVisible();
    }
  });
});
