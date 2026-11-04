import { test, expect } from '@playwright/test';
import { ADMIN_STATE, EMPLOYEE, EMPLOYEE_STATE } from './support/env';
import { capture, hasNoHorizontalOverflow } from './support/screenshots';

test.describe('移动端登录与导航', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('登录页适配、登录后打开导航抽屉', async ({ page }, testInfo) => {
    const project = testInfo.project.name;
    await page.goto('/login');
    await expect(page.getByRole('heading', { name: '登录', exact: true })).toBeVisible();
    const overflow = await hasNoHorizontalOverflow(page);
    expect(overflow.ok, JSON.stringify(overflow)).toBeTruthy();
    await capture(page, project, '01-login');

    await page.getByLabel('账号').fill(EMPLOYEE.username);
    await page.getByLabel('密码').fill(EMPLOYEE.password);
    await page.getByRole('button', { name: '登录', exact: true }).click();
    await expect(page).toHaveURL(/\/chat$/);
    await expect(page.getByRole('heading', { name: '有什么需要查询的？' })).toBeVisible();
    await capture(page, project, '02-chat-welcome');

    await page.getByRole('button', { name: '打开菜单' }).click();
    const drawer = page.getByRole('dialog', { name: '导航与最近对话' });
    await expect(drawer).toBeVisible();
    await expect(drawer.getByRole('link', { name: 'AI 助手' })).toBeVisible();
    await expect(drawer.getByRole('link', { name: '资料管理' })).toHaveCount(0);
    await capture(page, project, '03-menu');
    await drawer.getByRole('button', { name: '关闭菜单' }).click();
    await expect(drawer).toHaveCount(0);
  });
});

test.describe('移动端问答与来源', () => {
  test.use({ storageState: EMPLOYEE_STATE });

  test('提问、回答与来源抽屉在窄屏可用', async ({ page }, testInfo) => {
    const project = testInfo.project.name;
    await page.goto('/chat');
    await page.getByLabel('输入你的问题').fill('城东店的宣传海报放在哪里？');
    await page.getByRole('button', { name: '发送', exact: true }).click();

    const answer = page.locator('.message-assistant').last();
    await expect(answer).toContainText('B区1号货架第二层', { timeout: 15_000 });
    await expect(page.getByRole('button', { name: '发送', exact: true })).toBeVisible();

    const viewport = page.viewportSize();
    expect(viewport).not.toBeNull();
    const composerBox = await page.locator('.composer').boundingBox();
    expect(composerBox).not.toBeNull();
    if (composerBox && viewport) {
      expect(composerBox.y + composerBox.height).toBeLessThanOrEqual(viewport.height + 1);
    }
    const overflow = await hasNoHorizontalOverflow(page);
    expect(overflow.ok, JSON.stringify(overflow)).toBeTruthy();
    await capture(page, project, '04-chat-answer');

    await answer.getByRole('button', { name: '查看依据' }).first().click();
    const drawer = page.getByRole('dialog', { name: '来源详情' });
    await expect(drawer).toBeVisible();
    await expect(drawer).toContainText('B区1号货架第二层');
    const drawerBox = await drawer.boundingBox();
    if (drawerBox && viewport) {
      expect(drawerBox.width).toBeLessThanOrEqual(viewport.width + 1);
    }
    await capture(page, project, '05-source-drawer');
    await drawer.getByRole('button', { name: '关闭来源详情' }).click();
  });
});

test.describe('移动端管理边界', () => {
  test.use({ storageState: ADMIN_STATE });

  test('管理员在手机打开资料管理时提示使用电脑', async ({ page }, testInfo) => {
    const project = testInfo.project.name;
    await page.goto('/chat');
    await page.getByRole('button', { name: '打开菜单' }).click();
    const menu = page.getByRole('dialog', { name: '导航与最近对话' });
    await menu.getByRole('link', { name: '资料管理' }).click();
    await expect(page).toHaveURL(/\/documents$/);
    await expect(page.getByRole('heading', { name: '资料管理请在电脑上使用' })).toBeVisible();
    await expect(page.locator('.data-table')).toBeHidden();
    const overflow = await hasNoHorizontalOverflow(page);
    expect(overflow.ok, JSON.stringify(overflow)).toBeTruthy();
    await capture(page, project, '06-documents-mobile-notice');
  });
});
