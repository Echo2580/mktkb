import { test, expect } from '@playwright/test';
import {
  askViaUi,
  controlPost,
  openSession,
  shotFor,
  waitForAnswer,
  writeJson,
} from './support/acceptance';

/**
 * acceptance-05：来源链路。
 * - A-14：问答后「查看依据」→「来源详情」→ 定位信息 + 受保护原件（GET 200）；
 * - A-19：`scenario/delete {slot:"doc-guide"}` 删除 D03 后，旧消息来源抽屉显示
 *   「来源已失效，内容不可访问」「已删除」且无原件链接，原件 410；
 *   新会话再问 Q25 得到无依据/无匹配资料。
 *
 * 注意：本文件末尾删除 doc-guide，属于整套状态累积的一部分（后续 spec 06 不受影响）。
 */
const shot = shotFor('05-sources');

test.describe('A-14 来源抽屉与受保护原件', () => {
  test('Q01 回答 → 来源详情定位 + 原件 200', async ({ browser }) => {
    const { context, page } = await openSession(browser, 'employee');
    try {
      await page.goto('/chat');
      await askViaUi(page, '城东店的宣传海报在哪里？');
      const answer = await waitForAnswer(page);
      await expect(answer).toContainText('B区1号货架第二层', { timeout: 30_000 });
      await expect(answer.getByText('来源与依据')).toBeVisible();
      await shot(page, '01-a14-answer');

      await answer.getByRole('button', { name: '查看依据' }).first().click();
      const drawer = page.getByRole('dialog', { name: '来源详情' });
      await expect(drawer.getByRole('heading', { name: '来源详情' })).toBeVisible();
      await expect(drawer).toContainText('本次引用的内容');
      await expect(drawer).toContainText('B区1号货架第二层');
      await expect(drawer).toContainText('来源定位');
      await expect(drawer).toContainText('工作表 物品位置');
      await expect(drawer).toContainText('原始行号 8');
      await expect(drawer).toContainText('受保护原件');

      const fileLink = drawer.getByRole('link', { name: '在新窗口打开原件' });
      await expect(fileLink).toBeVisible();
      const fileHref = await fileLink.getAttribute('href');
      expect(fileHref).toBeTruthy();
      const fileResponse = await page.request.get(fileHref as string);
      expect(fileResponse.status()).toBe(200);
      expect(fileResponse.headers()['x-content-type-options']).toBe('nosniff');
      writeJson('a14-protected-file', {
        href: fileHref,
        status: 200,
        content_type: fileResponse.headers()['content-type'] ?? null,
        x_content_type_options: fileResponse.headers()['x-content-type-options'] ?? null,
      });
      await shot(page, '02-a14-source-drawer', { locator: drawer });

      await drawer.getByRole('button', { name: '关闭来源详情' }).click();
      await expect(drawer).toHaveCount(0);
    } finally {
      await context.close();
    }
  });
});

test.describe('A-19 资料删除后历史来源失效与新问答无依据', () => {
  test('删除 doc-guide：旧消息来源 410 失效，新会话 Q25 无匹配资料', async ({ browser, request }) => {
    const question = '领取活动物料需要哪些步骤？';
    const { context, page } = await openSession(browser, 'employee');
    try {
      // 1. 删除前：Q25 得到引用 D03 来源的回答
      await page.goto('/chat');
      await askViaUi(page, question);
      const before = await waitForAnswer(page);
      await expect(before.getByText('基于已发布资料')).toBeVisible({ timeout: 30_000 });
      const d03Bar = before.locator('.source-bar').filter({ hasText: 'D03_市场部工作指南.docx' }).first();
      await expect(d03Bar).toBeVisible({ timeout: 30_000 });
      await expect(page).toHaveURL(/\/chat\/[0-9a-fA-F-]{36}$/);
      const conversationId = new URL(page.url()).pathname.split('/').pop() as string;
      await shot(page, '03-a19-before-delete');

      await d03Bar.getByRole('button', { name: '查看依据' }).click();
      const drawer = page.getByRole('dialog', { name: '来源详情' });
      await expect(drawer.getByRole('heading', { name: '来源详情' })).toBeVisible();
      await expect(drawer).toContainText('D03_市场部工作指南.docx');
      const fileHref = await drawer.getByRole('link', { name: '在新窗口打开原件' }).getAttribute('href');
      expect(fileHref).toBeTruthy();
      await drawer.getByRole('button', { name: '关闭来源详情' }).click();
      await expect(drawer).toHaveCount(0);

      // 2. 删除 doc-guide（幂等控制路由，走产品删除接口）
      const deleted = await controlPost(request, '/__acceptance/scenario/delete', { slot: 'doc-guide' });
      expect(deleted.applied).toBe(true);
      writeJson('a19-delete-doc-guide', deleted);

      // 3. 原件接口对已删除资料返回 410
      const fileAfterDelete = await page.request.get(fileHref as string);
      expect(fileAfterDelete.status()).toBe(410);

      // 4. 旧会话重新打开：D03 来源抽屉显示失效态且无原件链接
      await page.goto(`/chat/${conversationId}`);
      const expiredBar = page
        .locator('.source-bar')
        .filter({ hasText: 'D03_市场部工作指南.docx' })
        .first();
      await expect(expiredBar).toBeVisible({ timeout: 30_000 });
      await expect(expiredBar).toContainText('已删除');
      await expiredBar.getByRole('button', { name: '查看依据' }).click();
      const expiredDrawer = page.getByRole('dialog', { name: '来源详情' });
      await expect(expiredDrawer).toContainText('来源已失效，内容不可访问', { timeout: 30_000 });
      await expect(expiredDrawer).toContainText('已删除');
      await expect(expiredDrawer.getByRole('link', { name: '在新窗口打开原件' })).toHaveCount(0);
      await shot(page, '04-a19-expired-source', { locator: expiredDrawer });
      await expiredDrawer.getByRole('button', { name: '关闭来源详情' }).click();
      await expect(expiredDrawer).toHaveCount(0);

      // 5. 新会话再问同一问题：不得再依据已删除的 D03。
      //    说明：B0 的 D09_物料领用通知（OCR 转录）也覆盖“领取活动物料前登记”，
      //    因此删除 doc-guide 后仍可能得到 answer；此时必须满足“来源中不再出现 D03”，
      //    若检索确实无结果则应为 not_found 且无来源区块。两种合法结果都如实落证据。
      await page.getByRole('link', { name: '新建对话' }).click();
      await expect(page).toHaveURL(/\/chat$/);
      await askViaUi(page, question);
      const after = await waitForAnswer(page);
      const afterText = await after.innerText();
      const hasNotFound = afterText.includes('无匹配资料');
      const citedDeletedSource =
        (await after.locator('.source-bar').filter({ hasText: 'D03_市场部工作指南.docx' }).count()) > 0;
      expect(citedDeletedSource, '新问答不得再引用已删除的 D03 来源').toBe(false);
      if (hasNotFound) {
        await expect(after.getByText('来源与依据')).toHaveCount(0);
      } else {
        await expect(after.getByText('基于已发布资料')).toBeVisible({ timeout: 30_000 });
        await expect(after.getByText('来源与依据')).toBeVisible();
      }
      writeJson('a19-after-delete-answer', {
        question,
        has_not_found_badge: hasNotFound,
        cited_deleted_source: citedDeletedSource,
        text: afterText.slice(0, 800),
        source_names: await after.locator('.source-bar-name').allInnerTexts(),
      });
      await shot(page, '05-a19-new-chat-no-evidence', { locator: after });
    } finally {
      await context.close();
    }
  });
});
