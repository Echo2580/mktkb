/**
 * T09-D3 B 层浏览器验收 · acceptance-08-mobile
 *
 * 覆盖冻结用例 A-28（移动端 390×844 / 375×844）：
 * - 员工真实 UI 登录（不是只用 API 会话），进入 AI 助手；
 * - 单轮问答必须可完成并展示来源；
 * - 来源抽屉可打开（「来源详情」）；
 * - 资料管理入口：员工侧不可见（抽屉导航无「资料管理」）且不可用（直接访问 /documents 被
 *   「资料管理仅限管理员」拦截）；管理员移动端访问 /documents 只显示 `.mobile-admin-notice`
 *   「资料管理请在电脑上使用」，桌面资料表格隐藏。
 *
 * 串行前提：07 已发布 V04/V06（位置/电话为新值），本 spec 只读状态、不重置数据。
 * 问答选择 Q03「城东店的展架在哪里？」——不受 C05/C06 冲突与 V04/V06 更新影响，串行下稳定。
 */
import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import { askViaUi, loginViaUi, shotFor, writeJson } from './support/acceptance';

const shot = shotFor('acceptance-08-mobile');

const QUESTION = '城东店的展架在哪里？';
const EXPECTED_ANSWER = 'A区2号货架底层';

function assistantCards(page: Page) {
  return page.locator('article.message-assistant[aria-label="知识库回答"]');
}

async function horizontalMetrics(page: Page) {
  return page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    innerWidth: window.innerWidth,
    bodyScrollWidth: document.body.scrollWidth,
  }));
}

async function expectNoHorizontalOverflow(page: Page, label: string) {
  const metrics = await horizontalMetrics(page);
  expect(metrics.scrollWidth, `${label} 出现横向溢出（真实页面必须适配移动宽度）`).toBeLessThanOrEqual(
    metrics.innerWidth + 1,
  );
  return metrics;
}

async function waitForSettledAnswer(page: Page, expectedCards: number) {
  await expect(assistantCards(page)).toHaveCount(expectedCards, { timeout: 120_000 });
  await expect(page.locator('.typing')).toHaveCount(0, { timeout: 120_000 });
  const card = assistantCards(page).last();
  await expect(card).toBeVisible({ timeout: 15_000 });
  return card;
}

async function askAndRead(page: Page, question: string) {
  const before = await assistantCards(page).count();
  await askViaUi(page, question);
  return waitForSettledAnswer(page, before + 1);
}

/** 员工真实 UI 登录并确认落在 AI 助手页。 */
async function loginEmployee(page: Page) {
  await page.goto('/login');
  await expect(page.locator('.login-form')).toBeVisible({ timeout: 30_000 });
  await loginViaUi(page, 'employee');
  await expect(page.locator('.topbar-title')).toHaveText('AI 助手', { timeout: 30_000 });
  await expect(page.locator('.topbar-badge')).toHaveText('员工');
}

async function openSourceDrawer(page: Page, card: ReturnType<typeof assistantCards>) {
  await card.getByRole('button', { name: '查看依据' }).first().click();
  const drawer = page.locator('aside.drawer[role="dialog"]');
  await expect(drawer).toBeVisible({ timeout: 15_000 });
  await expect(drawer.locator('.drawer-title')).toHaveText('来源详情');
  return drawer;
}

test.describe('A-28 移动端 · 390×844 员工', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('员工登录 / 单轮问答 / 来源抽屉 / 资料管理入口不可见不可用', async ({ page }) => {
    test.setTimeout(180_000);

    await page.goto('/login');
    await expect(page.locator('.login-form')).toBeVisible({ timeout: 30_000 });
    const loginMetrics = await expectNoHorizontalOverflow(page, '390 登录页');
    await shot(page, '390-login');

    await loginEmployee(page);
    // 移动断点：侧边栏隐藏，改用顶部菜单按钮
    await expect(page.locator('.app-sidebar')).toBeHidden();
    await expect(page.locator('button[aria-label="打开菜单"]')).toBeVisible();
    await expect(page.locator('.composer-textarea')).toBeVisible();
    await expectNoHorizontalOverflow(page, '390 会话页');
    await shot(page, '390-chat-employee');

    // 抽屉导航：员工只有 AI 助手，没有资料管理入口
    await page.locator('button[aria-label="打开菜单"]').click();
    const drawer = page.locator('aside.mobile-drawer[role="dialog"]');
    await expect(drawer).toBeVisible();
    const navLinks = drawer.locator('nav[aria-label="主要导航"] a');
    await expect(navLinks).toHaveCount(1);
    await expect(navLinks.first()).toContainText('AI 助手');
    await expect(drawer.getByText('资料管理')).toHaveCount(0);
    await shot(page, '390-employee-drawer-no-admin-entry');
    await page.locator('button[aria-label="关闭菜单"]').click();
    await expect(drawer).toHaveCount(0);

    // 单轮问答 + 来源
    const card = await askAndRead(page, QUESTION);
    await expect(card.locator('.assistant-head .badge')).toHaveText('基于已发布资料');
    await expect(card).toContainText(EXPECTED_ANSWER);
    await expect(card.getByText('来源与依据')).toBeVisible();
    await expectNoHorizontalOverflow(page, '390 问答结果');
    await shot(page, '390-chat-answer-with-source');

    const sourceDrawer = await openSourceDrawer(page, card);
    await expect(sourceDrawer.locator('.drawer-sub')).toContainText('物品位置表');
    await expect(sourceDrawer.locator('.drawer-body')).not.toBeEmpty();
    await shot(page, '390-source-drawer');
    await page.locator('button[aria-label="关闭来源详情"]').click();
    await expect(page.locator('aside.drawer[role="dialog"]')).toHaveCount(0);

    // 员工不可用资料管理：直接访问 /documents 被拦截
    await page.goto('/documents');
    const blocked = page.getByRole('alert');
    await expect(blocked).toContainText('资料管理仅限管理员');
    await expect(page.locator('.mobile-admin-notice')).toHaveCount(0);
    await expect(page.getByRole('button', { name: /上传资料/ })).toHaveCount(0);
    await expectNoHorizontalOverflow(page, '390 员工资料管理拦截页');
    await shot(page, '390-employee-documents-blocked');

    writeJson('acceptance-08-mobile/a28-390-employee', {
      case: 'A-28',
      viewport: { width: 390, height: 844 },
      login_overflow: loginMetrics,
      sidebar_hidden: true,
      employee_nav_items: ['AI 助手'],
      employee_can_see_documents_entry: false,
      employee_documents_blocked_notice: '资料管理仅限管理员',
      answer: { question: QUESTION, contains_expected: true, has_source_section: true },
      source_drawer: { title: '来源详情', subtitle_contains: '物品位置表' },
    });
  });
});

test.describe('A-28 移动端 · 375×844 员工', () => {
  test.use({ viewport: { width: 375, height: 844 } });

  test('员工登录 / 单轮问答 / 来源抽屉（375 宽度无横向溢出）', async ({ page }) => {
    test.setTimeout(180_000);

    await loginEmployee(page);
    await expect(page.locator('.app-sidebar')).toBeHidden();
    await expectNoHorizontalOverflow(page, '375 会话页');
    await shot(page, '375-chat-employee');

    const card = await askAndRead(page, QUESTION);
    await expect(card.locator('.assistant-head .badge')).toHaveText('基于已发布资料');
    await expect(card).toContainText(EXPECTED_ANSWER);
    await expectNoHorizontalOverflow(page, '375 问答结果');
    await shot(page, '375-chat-answer-with-source');

    const sourceDrawer = await openSourceDrawer(page, card);
    await expect(sourceDrawer.locator('.drawer-title')).toHaveText('来源详情');
    await expectNoHorizontalOverflow(page, '375 来源抽屉');
    await shot(page, '375-source-drawer');
    await page.locator('button[aria-label="关闭来源详情"]').click();

    writeJson('acceptance-08-mobile/a28-375-employee', {
      case: 'A-28',
      viewport: { width: 375, height: 844 },
      answer: { question: QUESTION, contains_expected: true },
      source_drawer: { title: '来源详情' },
    });
  });
});

test.describe('A-28 移动端 · 390×844 管理员资料管理提示', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('管理员移动端 /documents 只显示「资料管理请在电脑上使用」', async ({ page }) => {
    test.setTimeout(180_000);

    await page.goto('/login');
    await expect(page.locator('.login-form')).toBeVisible({ timeout: 30_000 });
    await loginViaUi(page, 'admin');
    await expect(page.locator('.topbar-title')).toHaveText('AI 助手', { timeout: 30_000 });

    await page.goto('/documents');
    const notice = page.locator('.mobile-admin-notice');
    await expect(notice).toBeVisible({ timeout: 30_000 });
    await expect(notice.getByRole('heading', { name: '资料管理请在电脑上使用' })).toBeVisible();
    await expect(notice).toContainText('手机端支持登录、问答、个人会话与来源查看');
    // 真实 UI：桌面资料表格在移动端隐藏，上传入口不可用
    await expect(page.locator('.doc-desktop')).toBeHidden();
    await expect(page.getByRole('button', { name: /上传资料/ })).toBeHidden();
    await expect(page.locator('table.data-table')).toBeHidden();
    await expectNoHorizontalOverflow(page, '390 管理员资料管理移动提示');
    await shot(page, '390-admin-documents-mobile-notice');

    // 提示中的返回入口可用（真实导航）
    await notice.getByRole('link', { name: /返回 AI 助手/ }).click();
    await expect(page.locator('.topbar-title')).toHaveText('AI 助手');

    writeJson('acceptance-08-mobile/a28-390-admin-documents-notice', {
      case: 'A-28',
      viewport: { width: 390, height: 844 },
      mobile_admin_notice: '资料管理请在电脑上使用',
      desktop_table_hidden: true,
      upload_button_hidden: true,
      return_entry_works: true,
    });
  });
});
