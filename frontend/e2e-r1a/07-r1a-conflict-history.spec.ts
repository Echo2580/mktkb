import fs from 'node:fs';
import { test, expect, type Page } from '@playwright/test';
import {
  EMPLOYEE,
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
import { capture } from './support/screenshots';

const seed = JSON.parse(fs.readFileSync(SEED_FILE, 'utf8')) as SeedData;
const QUESTION = '城东店的联系电话是什么？';
const NOTICE_NAME = 'V06_合作店家信息_新电话.xlsx';

async function loginIfNeeded(page: Page): Promise<void> {
  const composer = page.getByLabel('输入你的问题');
  if (await composer.isVisible().catch(() => false)) return;
  await page.getByLabel('账号').fill(EMPLOYEE.username);
  await page.getByLabel('密码').fill(EMPLOYEE.password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(composer).toBeVisible({ timeout: 15_000 });
}

test.describe('R1A 冲突来源与历史明细', () => {
  test.use({ storageState: EMPLOYEE_STATE });

  test('冲突值对应真实文件名/版本/定位，刷新重登重开仍可核对，删除后明确失效', async ({ page }) => {
    const admin = await openSession('admin');
    let createdId: string | null = null;
    try {
      const receipt = await uploadFile(admin, VARIANTS.newContacts);
      createdId = receipt.document.id;
      expect(runWorker().state).toBe('succeeded');
      await publishReceipt(admin, receipt);

      await page.goto('/chat');
      await page.getByLabel('输入你的问题').fill(QUESTION);
      await page.getByRole('button', { name: '发送', exact: true }).click();

      const answer = page.locator('.message-assistant').last();
      await expect(answer.getByText('资料记载不一致')).toBeVisible({ timeout: 15_000 });
      await expect(answer).toContainText('010-00000001');
      await expect(answer).toContainText('010-00000088');

      const phone01 = answer.locator('.conflict-entry').filter({ hasText: '010-00000001' });
      const phone88 = answer.locator('.conflict-entry').filter({ hasText: '010-00000088' });
      await expect(phone01).toContainText(seed.documents.D02.name);
      await expect(phone88).toContainText(NOTICE_NAME);
      await expect(phone01).toContainText('已发布');
      await expect(phone88).toContainText('已发布');
      await capture(page, 'r1a-functional', 'r1a-01-conflict-live');

      await phone01.getByRole('button', { name: '查看依据' }).click();
      let drawer = page.getByRole('dialog');
      await expect(drawer).toContainText('来源详情');
      await expect(drawer).toContainText(seed.documents.D02.name);
      await expect(drawer).toContainText('工作表 店家信息');
      await expect(drawer).toContainText('原始行号 5');
      await expect(drawer).toContainText('电话');
      await expect(drawer).toContainText('010-00000001');
      await expect(drawer.getByRole('link', { name: '在新窗口打开原件' })).toBeVisible();
      await drawer.getByRole('button', { name: '关闭来源详情' }).click();

      await phone88.getByRole('button', { name: '查看依据' }).click();
      drawer = page.getByRole('dialog');
      await expect(drawer).toContainText(NOTICE_NAME);
      await expect(drawer).toContainText('工作表 店家信息');
      await expect(drawer).toContainText('010-00000088');
      await drawer.getByRole('button', { name: '关闭来源详情' }).click();
      const conversationUrl = page.url();

      await page.reload();
      const refreshed = page.locator('.message-assistant').last();
      await expect(refreshed.getByText('资料记载不一致')).toBeVisible({ timeout: 15_000 });
      await expect(refreshed).toContainText('010-00000001');
      await expect(refreshed).toContainText('010-00000088');
      await expect(refreshed.locator('.conflict-entry').filter({ hasText: '010-00000001' })).toContainText(
        seed.documents.D02.name,
      );
      await expect(refreshed.locator('.conflict-entry').filter({ hasText: '010-00000088' })).toContainText(
        NOTICE_NAME,
      );
      await capture(page, 'r1a-functional', 'r1a-02-conflict-refresh');

      await page.getByRole('link', { name: '新建对话' }).click();
      await page.getByRole('navigation', { name: '最近对话' }).getByRole('link', { name: QUESTION }).click();
      const reopened = page.locator('.message-assistant').last();
      await expect(reopened.getByText('资料记载不一致')).toBeVisible({ timeout: 15_000 });
      await expect(reopened).toContainText(seed.documents.D02.name);
      await expect(reopened).toContainText(NOTICE_NAME);

      await page.getByRole('button', { name: '退出登录' }).click();
      await page.getByRole('dialog').getByRole('button', { name: '退出登录' }).click();
      await expect(page.getByLabel('账号')).toBeVisible({ timeout: 15_000 });
      await page.getByLabel('账号').fill(EMPLOYEE.username);
      await page.getByLabel('密码').fill(EMPLOYEE.password);
      await page.getByRole('button', { name: '登录', exact: true }).click();
      await page.goto(conversationUrl);
      const afterLogin = page.locator('.message-assistant').last();
      await expect(afterLogin.getByText('资料记载不一致')).toBeVisible({ timeout: 15_000 });
      await expect(afterLogin).toContainText('010-00000001');
      await expect(afterLogin).toContainText('010-00000088');
      await expect(afterLogin.locator('.conflict-entry').filter({ hasText: '010-00000088' })).toContainText(
        NOTICE_NAME,
      );
      await capture(page, 'r1a-functional', 'r1a-03-conflict-relogin');

      const revision = await getRevision(admin, createdId);
      await deleteDocument(admin, createdId, revision);
      createdId = null;

      await page.reload();
      const afterDelete = page.locator('.message-assistant').last();
      await expect(afterDelete.getByText('资料记载不一致')).toBeVisible({ timeout: 15_000 });
      await expect(afterDelete).toContainText('010-00000001');
      await expect(afterDelete).toContainText('010-00000088');
      const deletedEntry = afterDelete.locator('.conflict-entry').filter({ hasText: '010-00000088' });
      await expect(deletedEntry).toContainText(NOTICE_NAME);
      await expect(deletedEntry).toContainText('已删除');
      await deletedEntry.getByRole('button', { name: '查看依据' }).click();
      drawer = page.getByRole('dialog');
      await expect(drawer).toContainText('来源已失效，内容不可访问');
      await expect(drawer).toContainText('已删除');
      await expect(drawer.getByRole('link', { name: '在新窗口打开原件' })).toHaveCount(0);
      await drawer.getByRole('button', { name: '关闭来源详情' }).click();
      const activeEntry = afterDelete.locator('.conflict-entry').filter({ hasText: '010-00000001' });
      await activeEntry.getByRole('button', { name: '查看依据' }).click();
      drawer = page.getByRole('dialog');
      await expect(drawer).toContainText(seed.documents.D02.name);
      await expect(drawer).toContainText('010-00000001');
      await drawer.getByRole('button', { name: '关闭来源详情' }).click();
      await capture(page, 'r1a-functional', 'r1a-04-conflict-deleted');
    } finally {
      if (createdId) {
        const revision = await getRevision(admin, createdId).catch(() => null);
        if (revision !== null) await deleteDocument(admin, createdId, revision).catch(() => undefined);
      }
      await closeSession(admin);
    }
  });

  test('历史澄清候选刷新/重登后可重放且可继续追问，普通答案无回归', async ({ page }) => {
    await page.goto('/chat');
    await loginIfNeeded(page);
    await page.getByLabel('输入你的问题').fill('宣传海报在哪里？');
    await page.getByRole('button', { name: '发送', exact: true }).click();

    const answer = page.locator('.message-assistant').last();
    await expect(answer.getByText('需要确认')).toBeVisible({ timeout: 15_000 });
    const candidates = answer.locator('.candidate-button');
    await expect(candidates).toHaveCount(2);
    await expect(candidates.filter({ hasText: '城东店' })).toBeVisible();
    await expect(candidates.filter({ hasText: '城西店' })).toBeVisible();
    await capture(page, 'r1a-functional', 'r1a-05-clarification-live');
    const conversationUrl = page.url();

    await page.reload();
    const refreshed = page.locator('.message-assistant').last();
    await expect(refreshed.getByText('需要确认')).toBeVisible({ timeout: 15_000 });
    await expect(refreshed.locator('.candidate-button')).toHaveCount(2);
    await capture(page, 'r1a-functional', 'r1a-06-clarification-refresh');

    await page.getByRole('button', { name: '退出登录' }).click();
    await page.getByRole('dialog').getByRole('button', { name: '退出登录' }).click();
    await expect(page.getByLabel('账号')).toBeVisible({ timeout: 15_000 });
    await page.getByLabel('账号').fill(EMPLOYEE.username);
    await page.getByLabel('密码').fill(EMPLOYEE.password);
    await page.getByRole('button', { name: '登录', exact: true }).click();
    await page.goto(conversationUrl);
    const afterLogin = page.locator('.message-assistant').last();
    await expect(afterLogin.locator('.candidate-button')).toHaveCount(2, { timeout: 15_000 });
    await afterLogin.locator('.candidate-button').filter({ hasText: '城东店' }).click();
    await expect(page.locator('.message-assistant').last()).toContainText('B区1号货架第二层', {
      timeout: 15_000,
    });

    await page.getByRole('link', { name: '新建对话' }).click();
    await page.getByLabel('输入你的问题').fill('城东店的宣传海报放在哪里？');
    await page.getByRole('button', { name: '发送', exact: true }).click();
    const ordinary = page.locator('.message-assistant').last();
    await expect(ordinary.getByText('基于已发布资料')).toBeVisible({ timeout: 15_000 });
    await expect(ordinary).toContainText('B区1号货架第二层');
    const sourceBar = ordinary.locator('.source-bar').filter({ hasText: seed.documents.D01.name });
    await expect(sourceBar).toBeVisible();
    await sourceBar.getByRole('button', { name: '查看依据' }).click();
    const drawer = page.getByRole('dialog');
    await expect(drawer).toContainText('来源详情');
    await expect(drawer).toContainText(seed.documents.D01.name);
    await expect(drawer).toContainText('工作表 物品位置');
    await drawer.getByRole('button', { name: '关闭来源详情' }).click();
    await capture(page, 'r1a-functional', 'r1a-07-ordinary-answer');
  });
});
