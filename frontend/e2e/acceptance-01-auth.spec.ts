import { test, expect } from '@playwright/test';
import {
  askViaUi,
  loginViaUi,
  openSession,
  shotFor,
  waitForAnswer,
  writeJson,
} from './support/acceptance';

/**
 * acceptance-01：未登录跳转、管理员/员工角色入口（A-01/A-02）、
 * 以及 A-25 的会话与来源跨用户隔离（B 层浏览器部分）。
 *
 * 串行执行、状态累积：本文件在整套第一个运行；不假设干净 B0 之外的额外状态，
 * 所有会话隔离用例都自建全新会话与唯一问题。
 */
const shot = shotFor('01-auth');

test.describe('A-01 未登录访问业务页面跳转登录', () => {
  test('未登录访问 /chat 与 /documents 均跳 /login，auth/me=401', async ({ page }) => {
    await page.goto('/chat');
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole('heading', { name: '登录', exact: true })).toBeVisible();
    await expect(page.getByLabel('账号')).toBeVisible();
    await expect(page.getByLabel('密码')).toBeVisible();
    await shot(page, '01-chat-redirect-login');

    const me = await page.request.get('/api/v1/auth/me');
    expect(me.status()).toBe(401);

    await page.goto('/documents');
    await expect(page).toHaveURL(/\/login$/);
    await expect(page.getByRole('heading', { name: '登录', exact: true })).toBeVisible();
    await shot(page, '02-documents-redirect-login');
  });
});

test.describe('A-02 角色入口与权限', () => {
  test('管理员 UI 登录：资料管理入口 + 欢迎语 + 资料管理页', async ({ page }) => {
    await loginViaUi(page, 'admin');
    await expect(page.getByRole('heading', { name: '有什么需要查询的？' })).toBeVisible();
    const nav = page.getByRole('navigation', { name: '主要导航' });
    await expect(nav.getByRole('link', { name: '资料管理' })).toBeVisible();
    await shot(page, '03-admin-chat-entry');

    await nav.getByRole('link', { name: '资料管理' }).click();
    await expect(page).toHaveURL(/\/documents$/);
    await expect(page.getByRole('heading', { name: '资料管理', exact: true, level: 2 })).toBeVisible();
    await expect(page.locator('.data-table')).toBeVisible();
    await shot(page, '04-admin-documents');
  });

  test('员工 UI 登录：无资料管理入口，直达 /documents 受限且接口 403', async ({ page }) => {
    await loginViaUi(page, 'employee');
    await expect(page.getByRole('button', { name: '退出登录', exact: true })).toBeVisible();
    const nav = page.getByRole('navigation', { name: '主要导航' });
    await expect(nav.getByRole('link', { name: '资料管理' })).toHaveCount(0);
    await shot(page, '05-employee-chat-entry');

    await page.goto('/documents');
    await expect(page.getByText('资料管理仅限管理员')).toBeVisible();
    await expect(page.getByRole('link', { name: '返回 AI 助手' })).toBeVisible();
    await shot(page, '06-employee-documents-restricted');

    const forbidden = await page.request.get('/api/v1/documents');
    expect(forbidden.status()).toBe(403);
  });
});

test.describe('A-25 会话与来源跨用户隔离', () => {
  test('员工会话/来源对管理员不可见、直达 URL 被拒、跨用户来源接口非 200', async ({ browser }) => {
    const employee = await openSession(browser, 'employee');
    const admin = await openSession(browser, 'admin');
    try {
      const employeeQuestion = '城东店的宣传海报在哪里？';
      await employee.page.goto('/chat');
      await askViaUi(employee.page, employeeQuestion);
      const employeeAnswer = await waitForAnswer(employee.page);
      await expect(employeeAnswer).toContainText('B区1号货架第二层', { timeout: 30_000 });
      await expect(employeeAnswer.getByText('来源与依据')).toBeVisible();

      await expect(employee.page).toHaveURL(/\/chat\/[0-9a-fA-F-]{36}$/);
      const conversationId = new URL(employee.page.url()).pathname.split('/').pop() as string;
      expect(conversationId).toBeTruthy();

      interface MessageItem {
        id: string;
        role: string;
        sources?: Array<{ source_id: string; document_name: string }>;
      }
      const messagesResponse = await employee.context.request.get(
        `${new URL(employee.page.url()).origin}/api/v1/conversations/${conversationId}/messages?offset=0&limit=100`,
      );
      expect(messagesResponse.status()).toBe(200);
      const messages = (await messagesResponse.json()) as { items: MessageItem[] };
      const assistant = messages.items.filter((item) => item.role === 'assistant').pop();
      expect(assistant).toBeTruthy();
      const sources = assistant?.sources ?? [];
      expect(sources.length).toBeGreaterThan(0);
      const messageId = assistant?.id as string;
      const sourceId = sources[0].source_id;

      // 本人访问自己的来源 → 200
      const ownSource = await employee.context.request.get(
        `${new URL(employee.page.url()).origin}/api/v1/messages/${messageId}/sources/${sourceId}`,
      );
      expect(ownSource.status()).toBe(200);

      // 管理员会话列表里看不到员工会话。
      // 管理员此前未提问，先等待其列表加载出“还没有对话”空态，避免把“尚未渲染”误当隔离成功。
      await admin.page.goto('/chat');
      const adminNav = admin.page.getByRole('navigation', { name: '最近对话' });
      await expect(adminNav.getByText('还没有对话。发送第一个问题后会出现在这里。')).toBeVisible({
        timeout: 20_000,
      });
      await expect(adminNav.getByRole('link', { name: employeeQuestion })).toHaveCount(0);

      // 管理员直达员工会话 URL → 无权限/不存在提示
      await admin.page.goto(`/chat/${conversationId}`);
      await expect(
        admin.page.getByText(/会话不存在或已被删除|没有访问该会话的权限/),
      ).toBeVisible({ timeout: 20_000 });
      await shot(admin.page, '07-cross-user-conversation-denied');

      // 管理员跨用户读取员工来源 → 非 200
      const crossSource = await admin.context.request.get(
        `${new URL(admin.page.url()).origin}/api/v1/messages/${messageId}/sources/${sourceId}`,
      );
      expect(crossSource.status()).not.toBe(200);
      writeJson('a25-cross-user-source', {
        own_status: ownSource.status(),
        cross_status: crossSource.status(),
        conversation_id: conversationId,
        message_id: messageId,
        source_id: sourceId,
      });

      // 管理员自己的会话对员工也不可见
      const adminQuestion = '城西店的展架在哪里？';
      await admin.page.goto('/chat');
      await askViaUi(admin.page, adminQuestion);
      const adminAnswer = await waitForAnswer(admin.page);
      await expect(adminAnswer).toContainText('B区3号货架中层', { timeout: 30_000 });
      const adminNavAfter = admin.page.getByRole('navigation', { name: '最近对话' });
      await expect(adminNavAfter.getByRole('link', { name: adminQuestion })).toBeVisible();

      await employee.page.goto('/chat');
      const employeeNav = employee.page.getByRole('navigation', { name: '最近对话' });
      // 先证明列表已加载（员工自己的会话可见），再断言管理员的会话不可见。
      await expect(employeeNav.getByRole('link', { name: employeeQuestion })).toBeVisible();
      await expect(employeeNav.getByRole('link', { name: adminQuestion })).toHaveCount(0);
      await shot(employee.page, '08-employee-nav-isolated');
    } finally {
      await employee.context.close();
      await admin.context.close();
    }
  });
});
