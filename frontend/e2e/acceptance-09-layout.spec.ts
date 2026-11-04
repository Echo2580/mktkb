/**
 * T09-D3 B 层浏览器验收 · acceptance-09-layout
 *
 * 覆盖桌面三档视口下的真实页面布局取证与断言：
 *   - 1440×900（基准）、1366×768（常见笔记本）、1440×720（矮屏）
 * 每档都实际导航：未登录登录页 → 管理员登录 → 会话页（打开真实历史会话）→ 资料管理页，
 * 逐页断言关键结构可见、无横向溢出，并截图到 D3/screenshots/<label>/acceptance-09-layout/。
 *
 * 串行前提：07/08 已建立历史会话与已发布资料；本 spec 只读，不重置数据。
 */
import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { loginViaUi, shotFor, writeJson } from './support/acceptance';

const shot = shotFor('acceptance-09-layout');

interface ViewportSpec {
  key: string;
  width: number;
  height: number;
}

const VIEWPORTS: ViewportSpec[] = [
  { key: '1440x900', width: 1440, height: 900 },
  { key: '1366x768', width: 1366, height: 768 },
  { key: '1440x720', width: 1440, height: 720 },
];

async function expectNoHorizontalOverflow(page: Page, label: string) {
  const metrics = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
    innerHeight: window.innerHeight,
  }));
  expect(metrics.scrollWidth, `${label} 出现横向溢出`).toBeLessThanOrEqual(metrics.innerWidth + 1);
  return metrics;
}

async function assertViewportSize(page: Page, spec: ViewportSpec) {
  const size = await page.evaluate(() => ({ width: window.innerWidth, height: window.innerHeight }));
  expect(size.width).toBe(spec.width);
  expect(size.height).toBe(spec.height);
}

async function captureLayout(page: Page, spec: ViewportSpec) {
  // 1) 未登录登录页
  await page.goto('/login');
  await expect(page.locator('.login-card')).toBeVisible({ timeout: 30_000 });
  await expect(page.locator('.login-title')).toHaveText('登录');
  await assertViewportSize(page, spec);
  const loginOverflow = await expectNoHorizontalOverflow(page, `${spec.key} 登录页`);
  await shot(page, `${spec.key}-login`);

  // 2) 管理员登录 → 会话页（优先打开真实历史会话，否则退化为欢迎态）
  await loginViaUi(page, 'admin');
  await expect(page.locator('.topbar-title')).toHaveText('AI 助手', { timeout: 30_000 });
  // 桌面断点：侧边栏可见、移动菜单按钮隐藏
  await expect(page.locator('.app-sidebar')).toBeVisible();
  await expect(page.locator('button[aria-label="打开菜单"]')).toBeHidden();
  await expect(page.locator('.composer')).toBeVisible();
  await expect(page.locator('#question-input')).toBeVisible();

  const conversationLinks = page.locator('.conversation-item .conversation-title');
  const conversationCount = await conversationLinks.count();
  let chatState: 'conversation' | 'welcome' = 'welcome';
  if (conversationCount > 0) {
    await conversationLinks.first().click();
    await expect(page.locator('.chat-thread-title')).toBeVisible({ timeout: 30_000 });
    await expect(page.locator('.chat-thread-tag')).toHaveText('会话记录');
    await expect(page.locator('.message-list').first()).toBeVisible({ timeout: 30_000 });
    chatState = 'conversation';
  } else {
    await expect(page.locator('#welcome-title')).toBeVisible({ timeout: 30_000 });
  }
  const chatOverflow = await expectNoHorizontalOverflow(page, `${spec.key} 会话页`);
  await shot(page, `${spec.key}-chat`);

  // 3) 资料管理页（桌面表格可见，移动提示隐藏）
  await page.goto('/documents');
  await expect(page.locator('.page-title')).toHaveText('资料管理', { timeout: 30_000 });
  await expect(page.locator('.doc-desktop')).toBeVisible();
  await expect(page.locator('.mobile-admin-notice')).toBeHidden();
  await expect(page.locator('button', { hasText: '上传资料' }).first()).toBeVisible();
  const rows = page.locator('.doc-desktop table.data-table tbody tr');
  await expect(rows.first()).toBeVisible({ timeout: 30_000 });
  const rowCount = await rows.count();
  expect(rowCount).toBeGreaterThan(0);
  const documentsOverflow = await expectNoHorizontalOverflow(page, `${spec.key} 资料管理页`);
  await shot(page, `${spec.key}-documents`);

  return {
    viewport: spec,
    login: { overflow: loginOverflow },
    chat: { state: chatState, conversation_count: conversationCount, overflow: chatOverflow },
    documents: { row_count: rowCount, overflow: documentsOverflow },
  };
}

for (const spec of VIEWPORTS) {
  test.describe(`布局 ${spec.key}`, () => {
    test.use({ viewport: { width: spec.width, height: spec.height } });

    test(`${spec.key} 登录页/会话页/资料管理页真实导航与布局断言`, async ({ page }) => {
      test.setTimeout(180_000);
      const result = await captureLayout(page, spec);
      writeJson(`acceptance-09-layout/layout-${spec.key}`, result);
    });
  });
}
