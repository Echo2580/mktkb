import fs from 'node:fs';
import { test, expect } from '@playwright/test';
import {
  ADMIN_STATE,
  NORMAL,
  SEED_FILE,
  VARIANTS,
  type SeedData,
} from './support/env';
import { closeSession, deleteDocument, getRevision, openSession, publishReceipt, uploadFile } from './support/api';
import { runWorker } from './support/worker';

const seed = JSON.parse(fs.readFileSync(SEED_FILE, 'utf8')) as SeedData;

async function cleanupDocument(session: Awaited<ReturnType<typeof openSession>>, documentId: string): Promise<void> {
  const revision = await getRevision(session, documentId);
  await deleteDocument(session, documentId, revision);
}

test.describe('管理员资料生命周期', () => {
  test.use({ storageState: ADMIN_STATE });

  test('列表、搜索、筛选与提取内容检查', async ({ page }) => {
    await page.goto('/documents');
    await expect(page.getByRole('heading', { name: '资料管理', exact: true, level: 2 })).toBeVisible();
    await expect(page.locator('.data-table')).toContainText('D01_物品位置表.xlsx');
    await expect(page.locator('.data-table')).toContainText('D05_物料领用规范.pdf');
    await expect(page.locator('.record-count')).toContainText('5');

    const search = page.getByLabel('按文件名搜索');
    await search.fill('D02');
    await expect(page.locator('tbody tr')).toHaveCount(1);
    await expect(page.locator('tbody tr')).toContainText('D02_合作店家信息.xlsx');
    await search.fill('');
    await expect(page.locator('tbody tr')).toHaveCount(5);

    await page.getByLabel('按状态筛选').selectOption('published');
    await expect(page.locator('tbody tr')).toHaveCount(5);
    await page.getByLabel('按状态筛选').selectOption('');

    const row = page.locator('tbody tr').filter({ hasText: 'D01_物品位置表.xlsx' });
    await row.getByRole('button', { name: '查看/检查' }).click();
    const drawer = page.getByRole('dialog');
    await expect(drawer.getByRole('heading', { name: '查看 / 检查' })).toBeVisible();
    await expect(drawer).toContainText('处理完整');
    await expect(drawer).toContainText('有效数据行');
    await expect(drawer).toContainText('隐藏工作表');
    await expect(drawer).toContainText('原始行号 8');
    await expect(drawer).toContainText('B区1号货架第二层');
    await drawer.getByRole('button', { name: '关闭检查抽屉' }).click();
    await expect(drawer).toHaveCount(0);
  });

  test('上传、处理、检查并确认发布', async ({ page }) => {
    await page.goto('/documents');
    await page.getByRole('button', { name: '上传资料', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: '上传资料' })).toBeVisible();
    await dialog.locator('input[type=file]').setInputFiles(NORMAL.eventPlan);
    await expect(dialog).toContainText('D04_活动策划流程.docx');
    await dialog.getByRole('button', { name: '上传', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await expect(page.getByText(/已上传「D04_活动策划流程\.docx」/)).toBeVisible();

    const row = page.locator('tbody tr').filter({ hasText: 'D04_活动策划流程.docx' });
    await expect(row).toContainText('等待处理');

    const worker = runWorker();
    expect(worker.state).toBe('succeeded');
    await expect(row).toContainText('待确认', { timeout: 25_000 });

    await row.getByRole('button', { name: '查看/检查' }).click();
    const drawer = page.getByRole('dialog');
    await expect(drawer.getByRole('heading', { name: '检查待确认版本' })).toBeVisible();
    await expect(drawer).toContainText('活动申请至少提前 3 个工作日', { timeout: 15_000 });

    await drawer.getByRole('button', { name: '确认并发布' }).click();
    const confirm = page.getByRole('dialog', { name: /确认发布 V1/ });
    await expect(confirm).toBeVisible();
    await confirm.getByRole('button', { name: '确认发布', exact: true }).click();
    await expect(page.getByText('V1 已发布并生效')).toBeVisible({ timeout: 15_000 });

    await drawer.getByRole('button', { name: '关闭', exact: true }).click();
    await expect(row).toContainText('生效中');
    await expect(row).toContainText('当前版本已生效');
  });

  test('有效版与待确认新版并存，取消新版保留旧版', async ({ page }) => {
    await page.goto('/documents');
    const row = page.locator('tbody tr').filter({ hasText: 'D02_合作店家信息.xlsx' });
    await row.getByRole('button', { name: '替换', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: '替换资料' })).toBeVisible();
    await expect(dialog).toContainText('当前有效版本 V1');
    await dialog.locator('input[type=file]').setInputFiles(VARIANTS.newContacts);
    await dialog.getByRole('button', { name: '上传', exact: true }).click();
    await expect(dialog).toHaveCount(0);

    const worker = runWorker();
    expect(worker.state).toBe('succeeded');
    await expect(row).toContainText('待确认', { timeout: 25_000 });
    await expect(row).toContainText('生效 V1');
    await expect(row).toContainText('生效中');

    await row.getByRole('button', { name: '查看/检查' }).click();
    const drawer = page.getByRole('dialog');
    await expect(drawer.getByRole('heading', { name: '检查待确认版本' })).toBeVisible();
    await expect(drawer.getByRole('tab', { name: /V2 · 待确认/ })).toBeVisible();
    await expect(drawer.getByRole('tab', { name: /V1 · 已生效/ })).toBeVisible();

    await drawer.getByRole('button', { name: '取消版本' }).click();
    const confirm = page.getByRole('dialog', { name: /取消 V2/ });
    await expect(confirm).toBeVisible();
    await confirm.getByRole('button', { name: '取消版本', exact: true }).click();
    await expect(page.locator('.notice-area')).toContainText('V2 已取消', { timeout: 15_000 });
    await drawer.getByRole('button', { name: '关闭', exact: true }).click();
    await expect(row).toContainText('生效 V1');
    await expect(row).toContainText('V2 已取消');
    await expect(row).not.toContainText('待确认');
  });

  test('检查抽屉分页浏览来源单元', async ({ page }) => {
    const admin = await openSession('admin');
    let documentId = '';
    try {
      const receipt = await uploadFile(admin, seed.uploads.paging);
      const worker = runWorker();
      expect(worker.state).toBe('succeeded');
      await publishReceipt(admin, receipt);
      documentId = receipt.document.id;

      await page.goto('/documents');
      await page.getByLabel('按文件名搜索').fill('T08_分页测试表');
      const row = page.locator('tbody tr').filter({ hasText: 'T08_分页测试表.xlsx' });
      await expect(row).toHaveCount(1);
      await row.getByRole('button', { name: '查看/检查' }).click();

      const drawer = page.getByRole('dialog');
      await expect(drawer).toContainText('共 30 条来源单元 · 第 1 / 2 页', { timeout: 15_000 });
      await expect(drawer).toContainText('1–20 / 30');
      await drawer.getByRole('button', { name: '下一页' }).click();
      await expect(drawer).toContainText('21–30 / 30');
      await expect(drawer.getByRole('button', { name: '下一页' })).toBeDisabled();
      await drawer.getByRole('button', { name: '上一页' }).click();
      await expect(drawer).toContainText('1–20 / 30');
      await drawer.getByRole('button', { name: '关闭检查抽屉' }).click();
    } finally {
      if (documentId) await cleanupDocument(admin, documentId).catch(() => undefined);
      await closeSession(admin);
    }
    await page.reload();
    await expect(page.getByText('T08_分页测试表.xlsx')).toHaveCount(0);
  });

  test('同名冲突选择独立新增，重复字节被拒绝', async ({ page }) => {
    await page.goto('/documents');
    await page.getByRole('button', { name: '上传资料', exact: true }).click();
    let dialog = page.getByRole('dialog');
    await dialog.locator('input[type=file]').setInputFiles(seed.uploads.sameNameDifferentBytes);
    await dialog.getByRole('button', { name: '上传', exact: true }).click();

    await expect(dialog).toContainText('已存在同名资料');
    await expect(dialog.locator('.choice-item')).toHaveCount(1);
    await dialog.getByRole('button', { name: '作为独立资料新增' }).click();
    await expect(dialog).toHaveCount(0);
    await expect(page.getByText(/已上传「D01_物品位置表\.xlsx」/)).toBeVisible();

    const rows = page.locator('tbody tr').filter({ hasText: 'D01_物品位置表.xlsx' });
    await expect(rows).toHaveCount(2, { timeout: 20_000 });

    await rows.first().getByRole('button', { name: '删除', exact: true }).click();
    const deleteDialog = page.getByRole('dialog');
    await expect(deleteDialog).toContainText('删除此资料？');
    await deleteDialog.getByRole('button', { name: '删除资料', exact: true }).click();
    await expect(rows).toHaveCount(1, { timeout: 15_000 });

    await page.getByRole('button', { name: '上传资料', exact: true }).click();
    dialog = page.getByRole('dialog');
    await dialog.locator('input[type=file]').setInputFiles(NORMAL.positions);
    await dialog.getByRole('button', { name: '上传', exact: true }).click();
    await expect(dialog).toContainText('已存在同名资料');
    await dialog.getByRole('button', { name: '作为独立资料新增' }).click();
    await expect(dialog.locator('.form-error')).toContainText('字节完全相同');
    await dialog.getByRole('button', { name: '取消', exact: true }).click();
    await expect(dialog).toHaveCount(0);
  });

  test('损坏文件被拒绝并说明原因', async ({ page }) => {
    await page.goto('/documents');
    await page.getByRole('button', { name: '上传资料', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await dialog.locator('input[type=file]').setInputFiles(VARIANTS.corruptDocx);
    await dialog.getByRole('button', { name: '上传', exact: true }).click();
    await expect(dialog.locator('.form-error')).toBeVisible({ timeout: 15_000 });
    await expect(dialog).toContainText(/无法读取|损坏|格式|不支持/);
    await dialog.getByRole('button', { name: '取消', exact: true }).click();
    await expect(page.locator('.record-count')).toContainText('6');
  });

  test('扫描页遇 OCR 额度不足时任务阻塞、可重试并取消', async ({ page }) => {
    await page.goto('/documents');
    const row = page.locator('tbody tr').filter({ hasText: 'D06_店家资料维护说明.pdf' });
    await row.getByRole('button', { name: '替换', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: '替换资料' })).toBeVisible();
    await dialog.locator('input[type=file]').setInputFiles(VARIANTS.mixedScanPdf);
    await dialog.getByRole('button', { name: '上传', exact: true }).click();
    await expect(dialog).toHaveCount(0);

    const worker = runWorker();
    expect(['failed', 'blocked']).toContain(worker.state);
    expect(worker.error_code).toBe('OCR_QUOTA_UNAVAILABLE');

    await expect(row).toContainText('处理失败', { timeout: 25_000 });
    await expect(row).toContainText('生效 V1');
    await row.getByRole('button', { name: '查看/检查' }).click();

    const drawer = page.getByRole('dialog', { name: /查看 \/ 检查|检查待确认版本/ });
    await expect(drawer.getByRole('tab', { name: /V1 · 已生效/ })).toBeVisible();
    await expect(drawer).toContainText('OCR_QUOTA_UNAVAILABLE', { timeout: 15_000 });
    await expect(drawer).toContainText('已阻塞');
    const retry = drawer.getByRole('button', { name: '重试处理' });
    await expect(retry).toBeVisible();
    await retry.click();
    await expect(page.getByText(/V2 已重新排队处理/)).toBeVisible({ timeout: 15_000 });

    await drawer.getByRole('button', { name: '取消版本' }).click();
    const confirm = page.getByRole('dialog', { name: /取消 V2/ });
    await confirm.getByRole('button', { name: '取消版本', exact: true }).click();
    await expect(page.locator('.notice-area')).toContainText('V2 已取消', { timeout: 15_000 });
    await drawer.getByRole('button', { name: '关闭', exact: true }).click();
    await expect(row).toContainText('生效 V1');
    await expect(row).toContainText('V2 已取消');
  });

  test('删除资料后从列表移除', async ({ page }) => {
    await page.goto('/documents');
    const row = page.locator('tbody tr').filter({ hasText: 'D04_活动策划流程.docx' });
    await expect(row).toHaveCount(1);
    await row.getByRole('button', { name: '删除', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toContainText('删除此资料？');
    await dialog.getByRole('button', { name: '删除资料', exact: true }).click();
    await expect(page.locator('.notice-area')).toContainText('已删除', { timeout: 15_000 });
    await expect(row).toHaveCount(0);
  });
});
