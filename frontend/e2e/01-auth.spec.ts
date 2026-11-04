import { test, expect } from '@playwright/test';
import { ADMIN, EMPLOYEE } from './support/env';

test.describe('登录与角色入口', () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test('未登录访问业务页面时跳转登录', async ({ page }) => {
    await page.goto('/chat');
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole('heading', { name: '登录', exact: true })).toBeVisible();
    await expect(page.getByLabel('账号')).toBeVisible();
    await expect(page.getByLabel('密码')).toBeVisible();
    const me = await page.request.get('/api/v1/auth/me');
    expect(me.status()).toBe(401);
  });

  test('登录后回到原先访问的页面', async ({ page }) => {
    await page.goto('/documents');
    await expect(page).toHaveURL(/\/login$/);
    await page.getByLabel('账号').fill(ADMIN.username);
    await page.getByLabel('密码').fill(ADMIN.password);
    await page.getByRole('button', { name: '登录', exact: true }).click();
    await expect(page).toHaveURL(/\/documents$/);
    await expect(page.getByRole('heading', { name: '资料管理', exact: true, level: 2 })).toBeVisible();
  });

  test('错误凭据显示明确错误且可再次提交', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('账号').fill(ADMIN.username);
    await page.getByLabel('密码').fill('wrong-password');
    await page.getByRole('button', { name: '登录', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('账号或密码不正确');
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole('button', { name: '登录', exact: true })).toBeEnabled();
  });

  test('管理员登录后可见资料管理并可在确认后退出', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('账号').fill(ADMIN.username);
    await page.getByLabel('密码').fill(ADMIN.password);
    await page.getByRole('button', { name: '登录', exact: true }).click();
    await expect(page).toHaveURL(/\/chat$/);
    await expect(page.getByRole('heading', { name: '有什么需要查询的？' })).toBeVisible();
    await expect(page.getByRole('navigation', { name: '主要导航' }).getByRole('link', { name: '资料管理' })).toBeVisible();

    await page.getByRole('button', { name: '退出登录', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toContainText('退出登录？');
    await dialog.getByRole('button', { name: '退出登录', exact: true }).click();
    await expect(page).toHaveURL(/\/login$/);

    await page.goto('/chat');
    await expect(page).toHaveURL(/\/login$/);
  });

  test('员工登录后无资料管理入口，直达管理页显示受限', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('账号').fill(EMPLOYEE.username);
    await page.getByLabel('密码').fill(EMPLOYEE.password);
    await page.getByRole('button', { name: '登录', exact: true }).click();
    await expect(page).toHaveURL(/\/chat$/);
    await expect(page.getByRole('button', { name: '退出登录', exact: true })).toBeVisible();
    await expect(page.getByRole('navigation', { name: '主要导航' }).getByRole('link', { name: '资料管理' })).toHaveCount(0);

    await page.goto('/documents');
    await expect(page.getByText('资料管理仅限管理员')).toBeVisible();
    await expect(page.getByRole('link', { name: '返回 AI 助手' })).toBeVisible();
    const forbidden = await page.request.get('/api/v1/documents');
    expect(forbidden.status()).toBe(403);
  });

  test('登录页具备可访问名称与键盘提交', async ({ page }) => {
    await page.goto('/login');
    await page.getByLabel('账号').fill(EMPLOYEE.username);
    await page.getByLabel('密码').fill(EMPLOYEE.password);
    await page.getByLabel('密码').press('Enter');
    await expect(page).toHaveURL(/\/chat$/);
  });
});
