import { test, expect } from "@playwright/test";

test.describe("四页冒烟测试", () => {
  test("主页加载正常", async ({ page }) => {
    await page.goto("/");
    // 应该看到"新建项目"按钮
    await expect(page.getByRole("button", { name: /新建项目/ })).toBeVisible();
    // 底部状态栏
    await expect(page.getByText("MPC连接")).toBeVisible();
    await expect(page.getByText("Tokens")).toBeVisible();
  });

  test("任务页可导航", async ({ page }) => {
    await page.goto("/");
    await page.getByText("任务").click();
    // 任务页应该有某种内容（空状态或项目列表）
    await expect(page.locator("main, [data-testid='task-page']")).toBeVisible();
  });

  test("团队页可导航", async ({ page }) => {
    await page.goto("/");
    await page.getByText("团队").click();
    // 应该看到 Agents/Crews/Tools tab
    await expect(page.getByText("Agents")).toBeVisible();
  });

  test("设置页可导航", async ({ page }) => {
    await page.goto("/");
    await page.getByText("设置").click();
    // 应该看到 LLM/MCP/权限 tab
    await expect(page.getByText("LLM")).toBeVisible();
    await expect(page.getByText("MCP")).toBeVisible();
  });

  test("主题切换不崩溃", async ({ page }) => {
    await page.goto("/");
    // 找到主题切换按钮并点击
    const themeBtn = page.locator("button").filter({ hasText: /[☀️🌙💻]/ });
    if (await themeBtn.isVisible()) {
      await themeBtn.click();
      // 页面不应崩溃
      await expect(page.getByText("MyCrew")).toBeVisible();
    }
  });

  test("新建项目对话框可打开", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /新建项目/ }).click();
    // 应该出现 inception drawer/overlay
    await expect(page.locator("[data-testid='inception-drawer'], .fixed")).toBeVisible();
  });
});
