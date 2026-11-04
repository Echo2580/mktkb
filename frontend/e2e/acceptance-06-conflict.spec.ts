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
 * acceptance-06：C05 / C06 冲突卡片——两个取值、两条来源、各自「查看依据」可打开；
 * 且历史 V1（V03 的旧位置）不得作为当前来源出现。
 *
 * 前置：`/__acceptance/scenario/conflict {case}` 上传并发布 V01（C05）/ V02（C06），幂等。
 */
const shot = shotFor('06-conflict');

interface ConflictPayload {
  applied: boolean;
  case: string;
  question: string;
  expected_values: string[];
  expected_sources: Array<{ file: string }>;
  document_id: string;
  version_id: string;
  revision: number;
}

async function prepareConflict(request: import('@playwright/test').APIRequestContext, caseId: 'C05' | 'C06') {
  const payload = (await controlPost(request, '/__acceptance/scenario/conflict', { case: caseId })) as ConflictPayload;
  expect(payload.applied).toBe(true);
  expect(payload.question).toBeTruthy();
  expect(payload.expected_values.length).toBeGreaterThan(0);
  writeJson(`conflict-${caseId}-control`, {
    case: caseId,
    applied: payload.applied,
    question: payload.question,
    expected_values: payload.expected_values,
    expected_sources: payload.expected_sources,
    document_id: payload.document_id,
    version_id: payload.version_id,
    revision: payload.revision,
  });
  return payload;
}

test.describe('C05 位置冲突：两个有效值、两条来源', () => {
  test('城东店宣传海报现在放在哪里 → 资料记载不一致 + 两值两来源', async ({ browser, request }) => {
    const conflict = await prepareConflict(request, 'C05');
    const { context, page } = await openSession(browser, 'employee');
    try {
      await page.goto('/chat');
      await askViaUi(page, conflict.question);
      const answer = await waitForAnswer(page);
      await expect(answer.getByText('资料记载不一致')).toBeVisible({ timeout: 30_000 });
      await expect(answer).toContainText('B区1号货架第二层');
      await expect(answer).toContainText('D区暂存柜');
      // 历史业务 V1（版本号 1）与旧位置值不得作为冲突来源出现；
      // 注意 B0 的 doc-positions 槽文档名沿用首次导入的 V03 文件名（业务 V2 = version_number 2）。
      await expect(answer).not.toContainText('A区3号货架第二层');
      await expect(answer).toContainText('不会按上传时间自动裁定');

      const entries = answer.locator('.conflict-entry');
      await expect(entries).toHaveCount(2);
      await expect(answer.getByRole('button', { name: '查看依据' })).toHaveCount(2);

      const originalEntry = entries.filter({ hasText: 'B区1号货架第二层' });
      const changedEntry = entries.filter({ hasText: 'D区暂存柜' });
      await expect(originalEntry).toContainText('V03_物品位置表_历史V1.xlsx');
      await expect(originalEntry).toContainText('· V2');
      await expect(originalEntry).not.toContainText('· V1');
      await expect(changedEntry).toContainText('V01_临时物料位置通知.pdf');
      await expect(changedEntry).toContainText('· V1');
      await shot(page, '01-c05-conflict-card', { locator: answer });

      // 两条来源各自打开来源详情
      await originalEntry.getByRole('button', { name: '查看依据' }).click();
      let drawer = page.getByRole('dialog', { name: '来源详情' });
      await expect(drawer).toContainText('来源详情');
      await expect(drawer).toContainText('V03_物品位置表_历史V1.xlsx');
      await expect(drawer).toContainText('B区1号货架第二层');
      await expect(drawer).toContainText('工作表 物品位置');
      await expect(drawer).toContainText('原始行号 8');
      const d01Href = await drawer.getByRole('link', { name: '在新窗口打开原件' }).getAttribute('href');
      expect(d01Href).toBeTruthy();
      expect((await page.request.get(d01Href as string)).status()).toBe(200);
      await shot(page, '02-c05-source-d01', { locator: drawer });
      await drawer.getByRole('button', { name: '关闭来源详情' }).click();
      await expect(drawer).toHaveCount(0);

      await changedEntry.getByRole('button', { name: '查看依据' }).click();
      drawer = page.getByRole('dialog', { name: '来源详情' });
      await expect(drawer).toContainText('V01_临时物料位置通知.pdf');
      await expect(drawer).toContainText('D区暂存柜');
      await expect(drawer).toContainText('页码 1');
      await expect(drawer.getByRole('link', { name: '在新窗口打开原件' })).toBeVisible();
      await shot(page, '03-c05-source-v01', { locator: drawer });
      await drawer.getByRole('button', { name: '关闭来源详情' }).click();
      await expect(drawer).toHaveCount(0);
    } finally {
      await context.close();
    }
  });
});

test.describe('C06 电话冲突：两个有效值、两条来源', () => {
  test('城东店联系电话 → 资料记载不一致 + 010-00000001/010-00000099 两来源', async ({ browser, request }) => {
    const conflict = await prepareConflict(request, 'C06');
    const { context, page } = await openSession(browser, 'employee');
    try {
      await page.goto('/chat');
      await askViaUi(page, conflict.question);
      const answer = await waitForAnswer(page);
      await expect(answer.getByText('资料记载不一致')).toBeVisible({ timeout: 30_000 });
      await expect(answer).toContainText('010-00000001');
      await expect(answer).toContainText('010-00000099');
      // V06（新电话 010-00000088）在 C06 场景中不得出现
      await expect(answer).not.toContainText('010-00000088');

      const entries = answer.locator('.conflict-entry');
      await expect(entries).toHaveCount(2);
      await expect(answer.getByRole('button', { name: '查看依据' })).toHaveCount(2);

      const originalEntry = entries.filter({ hasText: '010-00000001' });
      const changedEntry = entries.filter({ hasText: '010-00000099' });
      await expect(originalEntry).toContainText('D02_合作店家信息.xlsx');
      await expect(originalEntry).toContainText('· V1');
      await expect(changedEntry).toContainText('V02_店家联系方式变更通知.pdf');
      await expect(changedEntry).toContainText('· V1');
      await shot(page, '04-c06-conflict-card', { locator: answer });

      await originalEntry.getByRole('button', { name: '查看依据' }).click();
      let drawer = page.getByRole('dialog', { name: '来源详情' });
      await expect(drawer).toContainText('来源详情');
      await expect(drawer).toContainText('D02_合作店家信息.xlsx');
      await expect(drawer).toContainText('010-00000001');
      await expect(drawer).toContainText('工作表 店家信息');
      await expect(drawer).toContainText('原始行号 5');
      const d02Href = await drawer.getByRole('link', { name: '在新窗口打开原件' }).getAttribute('href');
      expect(d02Href).toBeTruthy();
      expect((await page.request.get(d02Href as string)).status()).toBe(200);
      await shot(page, '05-c06-source-d02', { locator: drawer });
      await drawer.getByRole('button', { name: '关闭来源详情' }).click();
      await expect(drawer).toHaveCount(0);

      await changedEntry.getByRole('button', { name: '查看依据' }).click();
      drawer = page.getByRole('dialog', { name: '来源详情' });
      await expect(drawer).toContainText('V02_店家联系方式变更通知.pdf');
      await expect(drawer).toContainText('010-00000099');
      await expect(drawer).toContainText('页码 1');
      await expect(drawer.getByRole('link', { name: '在新窗口打开原件' })).toBeVisible();
      await shot(page, '06-c06-source-v02', { locator: drawer });
      await drawer.getByRole('button', { name: '关闭来源详情' }).click();
      await expect(drawer).toHaveCount(0);
    } finally {
      await context.close();
    }
  });
});
