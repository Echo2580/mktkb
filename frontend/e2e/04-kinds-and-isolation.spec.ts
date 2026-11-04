import fs from 'node:fs';
import { test, expect } from '@playwright/test';
import {
  ADMIN_STATE,
  BACKEND_URL,
  BASE_URL,
  EMPLOYEE_STATE,
  SEED_FILE,
  VARIANTS,
  type SeedData,
} from './support/env';
import {
  closeSession,
  deleteDocument,
  getRevision,
  openSession,
  publishReceipt,
  uploadFile,
} from './support/api';
import { runWorker } from './support/worker';

const seed = JSON.parse(fs.readFileSync(SEED_FILE, 'utf8')) as SeedData;

test.describe('异常结果、来源失效与会话隔离', () => {
  test.use({ storageState: EMPLOYEE_STATE });

  test('有效资料冲突显示两个值及各自可核对来源', async ({ page }) => {
    const admin = await openSession('admin');
    let createdId: string | null = null;
    try {
      const receipt = await uploadFile(admin, VARIANTS.newContacts);
      createdId = receipt.document.id;
      expect(runWorker().state).toBe('succeeded');
      await publishReceipt(admin, receipt);

      await page.goto('/chat');
      await page.getByLabel('输入你的问题').fill('城东店的联系电话是什么？');
      await page.getByRole('button', { name: '发送', exact: true }).click();

      const answer = page.locator('.message-assistant').last();
      await expect(answer.getByText('资料记载不一致')).toBeVisible({ timeout: 15_000 });
      await expect(answer).toContainText('010-00000001');
      await expect(answer).toContainText('010-00000088');
      const originalEntry = answer.locator('.conflict-entry').filter({ hasText: '010-00000001' });
      const changedEntry = answer.locator('.conflict-entry').filter({ hasText: '010-00000088' });
      await expect(originalEntry).toContainText('D02_合作店家信息.xlsx · V1');
      await expect(originalEntry).toContainText('工作表 店家信息');
      await expect(changedEntry).toContainText('V06_合作店家信息_新电话.xlsx · V1');
      await expect(changedEntry).toContainText('工作表 店家信息');
      await expect(answer.getByRole('button', { name: '查看依据' })).toHaveCount(2);

      await originalEntry.getByRole('button', { name: '查看依据' }).click();
      let drawer = page.getByRole('dialog');
      await expect(drawer).toContainText('来源详情');
      await expect(drawer).toContainText('D02_合作店家信息.xlsx');
      await expect(drawer).toContainText('010-00000001');
      await expect(drawer).toContainText('工作表 店家信息');
      await drawer.getByRole('button', { name: '关闭来源详情' }).click();

      await changedEntry.getByRole('button', { name: '查看依据' }).click();
      drawer = page.getByRole('dialog');
      await expect(drawer).toContainText('V06_合作店家信息_新电话.xlsx');
      await expect(drawer).toContainText('010-00000088');
      await expect(drawer).toContainText('工作表 店家信息');
      await drawer.getByRole('button', { name: '关闭来源详情' }).click();

      await expect(answer).toContainText('不会按上传时间自动裁定');
    } finally {
      if (createdId) {
        const revision = await getRevision(admin, createdId).catch(() => null);
        if (revision !== null) await deleteDocument(admin, createdId, revision).catch(() => undefined);
      }
      await closeSession(admin);
    }

    await page.getByRole('link', { name: '新建对话' }).click();
    await page.getByLabel('输入你的问题').fill('城东店的联系电话是什么？');
    await page.getByRole('button', { name: '发送', exact: true }).click();
    const restored = page.locator('.message-assistant').last();
    await expect(restored.getByText('基于已发布资料')).toBeVisible({ timeout: 15_000 });
    await expect(restored).toContainText('010-00000001');
    await expect(restored.getByText('资料记载不一致')).toHaveCount(0);
  });

  test('问答期间资料变更返回 knowledge_changed，历史来源随后失效', async ({ page, request }) => {
    const admin = await openSession('admin');
    const question = '店家资料修改时需要记录什么？';
    await page.goto('/chat');
    await page.getByLabel('输入你的问题').fill(question);
    await page.getByRole('button', { name: '发送', exact: true }).click();

    const firstAnswer = page.locator('.message-assistant').last();
    await expect(firstAnswer).toContainText('业务更新时间与修改原因', { timeout: 15_000 });
    const d06Bar = firstAnswer.locator('.source-bar').filter({ hasText: 'D06_店家资料维护说明.pdf' }).first();
    await expect(d06Bar).toBeVisible();
    await d06Bar.getByRole('button', { name: '查看依据' }).click();
    let drawer = page.getByRole('dialog');
    await expect(drawer).toContainText('来源详情');
    await expect(drawer).toContainText('已发布');
    await expect(drawer).toContainText('页码 1');
    const sourceFileHref = await drawer.getByRole('link', { name: '在新窗口打开原件' }).getAttribute('href');
    expect(sourceFileHref).toBeTruthy();
    await drawer.getByRole('button', { name: '关闭来源详情' }).click();

    const control = await request.post(`${BACKEND_URL}/__t08__/control`, { data: { slow_answer_ms: 6000 } });
    expect(control.ok()).toBeTruthy();

    await page.getByRole('link', { name: '新建对话' }).click();
    await page.getByLabel('输入你的问题').fill('领取活动物料需要哪些步骤？');
    await page.getByRole('button', { name: '发送', exact: true }).click();
    await expect(page.getByText('正在查找资料…')).toBeVisible();

    const revision = await getRevision(admin, seed.documents.D06.id);
    await deleteDocument(admin, seed.documents.D06.id, revision);
    const fileAfterDelete = await page.request.get(sourceFileHref as string);
    expect(fileAfterDelete.status()).toBe(410);

    const changed = page.locator('.message-assistant').last();
    await expect(changed.getByText('资料已更新', { exact: true })).toBeVisible({ timeout: 25_000 });
    await expect(changed.getByRole('button', { name: '重新查询' })).toBeVisible();

    await page.getByRole('navigation', { name: '最近对话' }).getByRole('link', { name: question }).click();
    await expect(page.locator('.message-assistant').first()).toContainText('业务更新时间与修改原因', { timeout: 15_000 });
    const expiredBar = page.locator('.source-bar').filter({ hasText: 'D06_店家资料维护说明.pdf' }).first();
    await expiredBar.getByRole('button', { name: '查看依据' }).click();
    drawer = page.getByRole('dialog');
    await expect(drawer).toContainText('来源已失效，内容不可访问', { timeout: 15_000 });
    await expect(drawer).toContainText('已删除');
    await expect(drawer.getByRole('link', { name: '在新窗口打开原件' })).toHaveCount(0);
    await drawer.getByRole('button', { name: '关闭来源详情' }).click();
    await closeSession(admin);
  });

  test('个人会话按账号隔离：管理员与员工互不可见', async ({ page, browser }) => {
    await page.goto('/chat');
    const employeeQuestion = '城北店的联系人是谁？';
    await page.getByLabel('输入你的问题').fill(employeeQuestion);
    await page.getByRole('button', { name: '发送', exact: true }).click();
    await expect(page.locator('.message-assistant').last()).toContainText('模拟联系人·李禾', { timeout: 15_000 });

    const adminContext = await browser.newContext({
      storageState: ADMIN_STATE,
      baseURL: BASE_URL,
      viewport: { width: 1440, height: 900 },
    });
    const adminPage = await adminContext.newPage();
    try {
      await adminPage.goto('/chat');
      const adminNav = adminPage.getByRole('navigation', { name: '最近对话' });
      await expect(adminNav.getByRole('link', { name: employeeQuestion })).toHaveCount(0);

      const adminQuestion = '滨河店的联系人是谁？';
      await adminPage.getByLabel('输入你的问题').fill(adminQuestion);
      await adminPage.getByRole('button', { name: '发送', exact: true }).click();
      await expect(adminPage.locator('.message-assistant').last()).toContainText('模拟联系人·周安', { timeout: 15_000 });
      await expect(adminNav.getByRole('link', { name: adminQuestion })).toBeVisible();

      await page.goto('/chat');
      const employeeNav = page.getByRole('navigation', { name: '最近对话' });
      await expect(employeeNav.getByRole('link', { name: adminQuestion })).toHaveCount(0);
      await expect(employeeNav.getByRole('link', { name: employeeQuestion })).toBeVisible();
    } finally {
      await adminContext.close();
    }
  });
});
