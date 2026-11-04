import { test, expect } from '@playwright/test';
import { ADMIN_STATE, BASE_URL } from './support/env';
import { capture, hasNoHorizontalOverflow } from './support/screenshots';

test.describe('桌面视口布局与截图', () => {
  test.use({ storageState: ADMIN_STATE });

  test('助手、资料管理与检查抽屉在目标视口完整可用', async ({ page, browser }, testInfo) => {
    const project = testInfo.project.name;
    const viewport = page.viewportSize();
    expect(viewport).not.toBeNull();

    await page.goto('/chat');
    await expect(page.getByRole('heading', { name: '有什么需要查询的？' })).toBeVisible();
    let overflow = await hasNoHorizontalOverflow(page);
    expect(overflow.ok, JSON.stringify(overflow)).toBeTruthy();
    const composer = await page.locator('.composer').boundingBox();
    if (composer && viewport) {
      expect(composer.y + composer.height).toBeLessThanOrEqual(viewport.height + 1);
    }
    await capture(page, project, '01-chat-welcome');

    await page.goto('/documents');
    await expect(page.locator('.data-table')).toContainText('D01_物品位置表.xlsx');
    await expect(page.locator('.data-table')).toBeVisible();
    overflow = await hasNoHorizontalOverflow(page);
    expect(overflow.ok, JSON.stringify(overflow)).toBeTruthy();
    await capture(page, project, '02-documents-list');

    const row = page.locator('tbody tr').filter({ hasText: 'D01_物品位置表.xlsx' });
    const trigger = row.getByRole('button', { name: '查看/检查' });
    await trigger.click();
    const drawer = page.getByRole('dialog', { name: /查看 \/ 检查|检查待确认版本/ });
    await expect(drawer).toBeVisible();
    await expect(drawer).toContainText('处理完整', { timeout: 15_000 });
    await expect(drawer.locator('.preview-unit').first()).toBeVisible({ timeout: 15_000 });
    await capture(page, project, '03-documents-drawer');
    await drawer.getByRole('button', { name: '关闭检查抽屉' }).click();
    await expect(drawer).toHaveCount(0);
    await expect(trigger).toBeFocused();

    await trigger.click();
    await expect(drawer).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(drawer).toHaveCount(0);
    await expect(trigger).toBeFocused();

    const anonymous = await browser.newContext({
      storageState: { cookies: [], origins: [] },
      baseURL: BASE_URL,
      viewport: viewport ?? { width: 1440, height: 900 },
    });
    const loginPage = await anonymous.newPage();
    try {
      await loginPage.goto('/login');
      await expect(loginPage.getByRole('heading', { name: '登录', exact: true })).toBeVisible();
      await loginPage.evaluate(() => document.fonts.ready);
      await capture(loginPage, project, '04-login');
    } finally {
      await anonymous.close();
    }
  });
});
