import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test, expect, type Locator, type Page } from '@playwright/test';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(HERE, '../..');
const FIXTURES = path.join(PROJECT_ROOT, 'fixtures/acceptance/normal');
const EVIDENCE_ROOT = process.env.S3_REAL_EVIDENCE_ROOT
  ? path.resolve(process.env.S3_REAL_EVIDENCE_ROOT)
  : path.join(PROJECT_ROOT, 'docs/evidence/LOCAL-R1-20261101/S3-DEV');
const LABEL = process.env.S3_REAL_RUN_LABEL || 'manual';

const ADMIN_USERNAME = 'admin';
const ADMIN_PASSWORD = process.env.S3_REAL_ADMIN_PASSWORD || '';

interface VersionSummary {
  id: string;
  number: number;
  state: string;
  processing_report?: Record<string, unknown> | null;
}

interface DocumentSummary {
  id: string;
  name: string;
  file_type: string;
  latest_version: VersionSummary | null;
  active_version: VersionSummary | null;
  deleted: boolean;
}

interface UploadReceipt {
  document: DocumentSummary;
  version: VersionSummary;
  job: { id: string; state: string; version_id?: string };
}

interface DocumentDetail {
  document: DocumentSummary;
  versions: VersionSummary[];
  jobs: Array<{ id: string; state: string; version_id: string }>;
  revision: number;
}

async function writeEvidence(name: string, payload: unknown): Promise<string> {
  const target = path.join(EVIDENCE_ROOT, 'actual', `real-${LABEL}-${name}.json`);
  await fs.mkdir(path.dirname(target), { recursive: true });
  await fs.writeFile(target, `${JSON.stringify(payload, null, 2)}\n`, 'utf8');
  return target;
}

async function shot(page: Page, name: string, locator?: Locator): Promise<string> {
  const target = path.join(EVIDENCE_ROOT, 'screenshots', 'real', `${LABEL}-${name}.png`);
  await fs.mkdir(path.dirname(target), { recursive: true });
  if (locator) {
    await locator.scrollIntoViewIfNeeded();
    await locator.screenshot({ path: target, animations: 'disabled' });
  } else {
    await page.screenshot({ path: target, fullPage: true, animations: 'disabled' });
  }
  return target;
}

function trackRequests(page: Page): string[] {
  const urls: string[] = [];
  page.on('request', (request) => urls.push(request.url()));
  return urls;
}

function expectLoopbackOnly(urls: string[]): void {
  const external = urls.filter((url) => {
    try {
      const parsed = new URL(url);
      return !['127.0.0.1', 'localhost', '::1', '[::1]'].includes(parsed.hostname)
        && !['data:', 'blob:', 'about:'].includes(parsed.protocol);
    } catch {
      return false;
    }
  });
  expect(external, `检测到非回环请求：${JSON.stringify(external)}`).toEqual([]);
}

function captureUploads(page: Page): UploadReceipt[] {
  const receipts: UploadReceipt[] = [];
  page.on('response', (response) => {
    const request = response.request();
    const pathname = new URL(response.url()).pathname;
    if (request.method() === 'POST' && /\/api\/v1\/documents$/.test(pathname) && response.status() === 202) {
      void response.json().then((body) => receipts.push(body as UploadReceipt)).catch(() => undefined);
    }
  });
  return receipts;
}

async function loginAdmin(page: Page): Promise<void> {
  if (!ADMIN_PASSWORD) throw new Error('缺少 S3_REAL_ADMIN_PASSWORD');
  await page.goto('/login');
  await page.getByLabel('账号').fill(ADMIN_USERNAME);
  await page.getByLabel('密码').fill(ADMIN_PASSWORD);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page).toHaveURL(/\/chat$/);
  await page.goto('/documents');
  await expect(page.getByRole('heading', { name: '资料管理', exact: true, level: 2 })).toBeVisible();
}

async function listDocuments(page: Page): Promise<{ items: DocumentSummary[]; total: number }> {
  const response = await page.request.get('/api/v1/documents?limit=100');
  expect(response.status(), await response.text()).toBe(200);
  return (await response.json()) as { items: DocumentSummary[]; total: number };
}

async function getDetail(page: Page, documentId: string): Promise<DocumentDetail> {
  const response = await page.request.get(`/api/v1/documents/${documentId}`);
  expect(response.status(), await response.text()).toBe(200);
  return (await response.json()) as DocumentDetail;
}

async function getPreview(page: Page, documentId: string, versionId: string): Promise<any> {
  const response = await page.request.get(
    `/api/v1/documents/${documentId}/versions/${versionId}/preview?offset=0&limit=20`,
  );
  expect(response.status(), await response.text()).toBe(200);
  return response.json();
}

async function waitForReview(page: Page, documentId: string, timeoutMs = 120_000): Promise<DocumentDetail> {
  const deadline = Date.now() + timeoutMs;
  let last: DocumentDetail | null = null;
  while (Date.now() < deadline) {
    last = await getDetail(page, documentId);
    const state = last.document.latest_version?.state;
    if (state === 'review_required') return last;
    if (state === 'failed') {
      throw new Error(`资料处理失败：${JSON.stringify(last.document.latest_version?.processing_report ?? null)}`);
    }
    await page.waitForTimeout(500);
  }
  throw new Error(`等待待确认状态超时：${documentId} 最后状态 ${last?.document.latest_version?.state ?? 'unknown'}`);
}

async function inspectAndPublish(
  page: Page,
  name: string,
  expectedText: string,
  shotName: string,
  pendingOnly = false,
): Promise<string> {
  await page.reload();
  await expect(page.getByRole('heading', { name: '资料管理', exact: true, level: 2 })).toBeVisible();
  let row = page.locator('tbody tr').filter({ hasText: name });
  if (pendingOnly) row = row.filter({ hasText: '待确认' });
  await expect(row).toHaveCount(1);
  await row.getByRole('button', { name: '查看/检查' }).click();
  const drawer = page.getByRole('dialog');
  await expect(drawer.getByRole('heading', { name: '检查待确认版本' })).toBeVisible();
  await expect(drawer).toContainText('处理报告');
  await expect(drawer).toContainText('处理完整');
  await expect(drawer).toContainText(expectedText, { timeout: 30_000 });
  await expect(drawer.locator('.preview-unit').first()).toBeVisible({ timeout: 30_000 });
  const screenshot = await shot(page, shotName, drawer);

  await drawer.getByRole('button', { name: '确认并发布' }).click();
  const confirm = page.getByRole('dialog', { name: /确认发布 V1/ });
  await expect(confirm).toBeVisible();
  await confirm.getByRole('button', { name: '确认发布', exact: true }).click();
  await expect(page.locator('.notice-area')).toContainText('V1 已发布并生效', { timeout: 30_000 });
  await shot(page, `${shotName}-published`);
  await drawer.getByRole('button', { name: '关闭检查抽屉' }).click();
  await expect(drawer).toHaveCount(0);
  if (!pendingOnly) {
    await expect(page.locator('tbody tr').filter({ hasText: name })).toContainText('当前版本已生效');
  }
  return screenshot;
}

async function chooseFolder(page: Page, folder: string) {
  await page.getByRole('button', { name: '上传文件夹', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '上传文件夹' });
  await dialog.locator('input[type=file]').setInputFiles(folder);
  return dialog;
}

test.describe.serial('S3 实际本地后端文件夹上传', () => {
  test('docx/xlsx/文字PDF 递归上传、真实解析、检查并发布', async ({ page }, info) => {
    const requests = trackRequests(page);
    const folder = info.outputPath('S3资料');
    await fs.mkdir(path.join(folder, 'A-正常'), { recursive: true });
    await fs.mkdir(path.join(folder, 'B-跳过'), { recursive: true });
    await fs.copyFile(path.join(FIXTURES, 'D03_市场部工作指南.docx'), path.join(folder, 'A-正常/D03_市场部工作指南.docx'));
    await fs.copyFile(path.join(FIXTURES, 'D01_物品位置表.xlsx'), path.join(folder, 'A-正常/D01_物品位置表.xlsx'));
    await fs.copyFile(path.join(FIXTURES, 'D05_物料领用规范.pdf'), path.join(folder, 'A-正常/D05_物料领用规范.pdf'));
    await fs.writeFile(path.join(folder, 'B-跳过/说明.txt'), 'unsupported');
    await fs.writeFile(path.join(folder, 'B-跳过/空文件.xlsx'), '');

    await loginAdmin(page);
    const receipts = captureUploads(page);
    const dialog = await chooseFolder(page, folder);
    await expect(dialog).toContainText('待上传 3');
    await expect(dialog).toContainText('已跳过 2');
    await shot(page, '01-folder-queue');

    await dialog.getByRole('button', { name: '开始上传', exact: true }).click();
    await expect(dialog).toContainText('已上传 3');
    await expect.poll(() => receipts.length, { timeout: 15_000 }).toBe(3);
    await shot(page, '02-folder-uploaded');
    await dialog.getByRole('button', { name: '关闭', exact: true }).click();
    await expect(dialog).toHaveCount(0);

    await expect.poll(async () => (await listDocuments(page)).items.length, { timeout: 30_000 }).toBe(3);
    const initial = await listDocuments(page);
    const names = initial.items.map((item) => item.name).sort();
    expect(names).toEqual(['D01_物品位置表.xlsx', 'D03_市场部工作指南.docx', 'D05_物料领用规范.pdf']);
    for (const item of initial.items) {
      expect(item.name).not.toMatch(/[\\/]/);
      expect(item.deleted).toBe(false);
    }

    const expected: Record<string, string> = {
      'D03_市场部工作指南.docx': '物料领用',
      'D01_物品位置表.xlsx': 'B区1号货架第二层',
      'D05_物料领用规范.pdf': '领用范围',
    };
    const records: Array<Record<string, unknown>> = [];
    for (const receipt of receipts) {
      const detail = await waitForReview(page, receipt.document.id);
      expect(detail.jobs.length).toBeGreaterThan(0);
      const job = detail.jobs.find((item) => item.version_id === receipt.version.id) ?? detail.jobs[0];
      expect(job.state).toBe('succeeded');
      const latest = detail.document.latest_version;
      expect(latest?.id).toBe(receipt.version.id);
      expect(latest?.state).toBe('review_required');
      const preview = await getPreview(page, receipt.document.id, receipt.version.id);
      expect(preview.total).toBeGreaterThan(0);
      expect(preview.items.length).toBeGreaterThan(0);
      expect(JSON.stringify(preview.items)).toContain(expected[receipt.document.name]);
      records.push({
        name: receipt.document.name,
        document_id: receipt.document.id,
        version_id: receipt.version.id,
        job_id: receipt.job.id,
        job_state: job.state,
        preview_total: preview.total,
        report: latest?.processing_report ?? null,
      });
    }
    expect(records).toHaveLength(3);

    await writeEvidence('folder-batch-parsed', { names, records });
    for (const record of records) {
      await inspectAndPublish(
        page,
        String(record.name),
        expected[String(record.name)],
        `03-inspect-${String(record.name).replace(/\.[^.]+$/, '')}`,
      );
      const detail = await getDetail(page, String(record.document_id));
      expect(detail.document.latest_version?.state).toBe('published');
      expect(detail.document.active_version?.id).toBe(record.version_id);
    }

    const published = await listDocuments(page);
    expect(published.items).toHaveLength(3);
    expect(published.items.every((item) => item.active_version?.state === 'published')).toBe(true);
    await writeEvidence('folder-batch-published', {
      names,
      documents: published.items.map((item) => ({
        id: item.id,
        name: item.name,
        active_version: item.active_version?.number,
        latest_state: item.latest_version?.state,
      })),
    });
    await shot(page, '04-folder-published-list');
    expectLoopbackOnly(requests);
  });

  test('重复字节不建资料，同名冲突显式新增后可检查发布', async ({ page }, info) => {
    const requests = trackRequests(page);
    const folder = info.outputPath('S3重复与同名');
    await fs.mkdir(path.join(folder, 'A-重复'), { recursive: true });
    await fs.mkdir(path.join(folder, 'B-同名'), { recursive: true });
    await fs.mkdir(path.join(folder, 'C-忽略'), { recursive: true });
    await fs.copyFile(path.join(FIXTURES, 'D03_市场部工作指南.docx'), path.join(folder, 'A-重复/D03_市场部工作指南-副本.docx'));
    await fs.copyFile(path.join(FIXTURES, 'D04_活动策划流程.docx'), path.join(folder, 'B-同名/D03_市场部工作指南.docx'));
    await fs.writeFile(path.join(folder, 'C-忽略/说明.txt'), 'unsupported');

    await loginAdmin(page);
    const before = await listDocuments(page);
    const beforeIds = new Set(before.items.map((item) => item.id));
    const receipts = captureUploads(page);
    const dialog = await chooseFolder(page, folder);
    await expect(dialog).toContainText('待上传 2');
    await expect(dialog).toContainText('已跳过 1');
    await dialog.getByRole('button', { name: '开始上传', exact: true }).click();
    await expect(dialog).toContainText('待确认 1');
    await expect(dialog).toContainText('已跳过 2');
    await expect(dialog).toContainText('内容已存在，未创建重复资料。');
    await shot(page, '05-duplicate-and-same-name');

    const afterDuplicate = await listDocuments(page);
    expect(afterDuplicate.items).toHaveLength(before.items.length);
    expect(afterDuplicate.items.some((item) => item.name.includes('副本'))).toBe(false);

    const conflictRow = dialog.locator('.folder-upload-list li').filter({ hasText: 'D03_市场部工作指南.docx' });
    await conflictRow.getByRole('button', { name: '处理同名文件', exact: true }).click();
    const nested = page.getByRole('dialog', { name: '上传资料' });
    await nested.getByRole('button', { name: '上传', exact: true }).click();
    await expect(nested).toContainText('已存在同名资料');
    await nested.getByRole('button', { name: '作为独立资料新增', exact: true }).click();
    await expect(conflictRow).toContainText('已上传，等待处理');
    await expect.poll(() => receipts.length, { timeout: 15_000 }).toBe(1);
    await shot(page, '06-same-name-added');
    await dialog.getByRole('button', { name: '关闭', exact: true }).click();
    await expect(dialog).toHaveCount(0);

    const afterAdd = await listDocuments(page);
    expect(afterAdd.items).toHaveLength(4);
    const sameName = afterAdd.items.filter((item) => item.name === 'D03_市场部工作指南.docx');
    expect(sameName).toHaveLength(2);
    expect(new Set(sameName.map((item) => item.id)).size).toBe(2);
    const added = sameName.find((item) => !beforeIds.has(item.id));
    expect(added).toBeTruthy();
    expect(added?.id).toBe(receipts[0].document.id);

    const detail = await waitForReview(page, String(added?.id));
    expect(detail.jobs.some((job) => job.version_id === receipts[0].version.id && job.state === 'succeeded')).toBe(true);
    const preview = await getPreview(page, String(added?.id), receipts[0].version.id);
    expect(JSON.stringify(preview.items)).toContain('活动申请至少提前 3 个工作日');
    await inspectAndPublish(page, 'D03_市场部工作指南.docx', '活动申请至少提前 3 个工作日', '07-same-name-inspect', true);

    const finalList = await listDocuments(page);
    expect(finalList.items).toHaveLength(4);
    expect(finalList.items.filter((item) => item.name === 'D03_市场部工作指南.docx')).toHaveLength(2);
    expect(finalList.items.filter((item) => item.name.includes('副本'))).toHaveLength(0);
    expect(finalList.items.filter((item) => item.name === 'D03_市场部工作指南.docx').every((item) => item.active_version?.state === 'published')).toBe(true);
    await writeEvidence('same-name-duplicate', {
      before: before.items.map((item) => ({ id: item.id, name: item.name })),
      after: finalList.items.map((item) => ({
        id: item.id,
        name: item.name,
        active_version: item.active_version?.number,
        latest_state: item.latest_version?.state,
      })),
      duplicate_document_created: finalList.items.some((item) => item.name.includes('副本')),
      added_document_id: added?.id,
      receipts: receipts.map((item) => ({ document_id: item.document.id, version_id: item.version.id, job_id: item.job.id })),
      preview_total: preview.total,
    });
    await shot(page, '08-final-list');
    expectLoopbackOnly(requests);
  });

  test('单文件上传原流程回归：上传、解析、检查、发布', async ({ page }) => {
    const requests = trackRequests(page);
    await loginAdmin(page);
    const receipts = captureUploads(page);
    await page.getByRole('button', { name: '上传资料', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: '上传资料' })).toBeVisible();
    await dialog.locator('input[type=file]').setInputFiles(path.join(FIXTURES, 'D02_合作店家信息.xlsx'));
    await expect(dialog).toContainText('D02_合作店家信息.xlsx');
    await dialog.getByRole('button', { name: '上传', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    await expect(page.locator('.notice-area')).toContainText('已上传「D02_合作店家信息.xlsx」');
    await expect.poll(() => receipts.length, { timeout: 15_000 }).toBe(1);

    const detail = await waitForReview(page, receipts[0].document.id);
    expect(detail.document.name).toBe('D02_合作店家信息.xlsx');
    expect(detail.jobs.some((job) => job.version_id === receipts[0].version.id && job.state === 'succeeded')).toBe(true);
    const preview = await getPreview(page, receipts[0].document.id, receipts[0].version.id);
    expect(JSON.stringify(preview.items)).toContain('城东店');
    await shot(page, '09-single-upload-queued');
    await inspectAndPublish(page, 'D02_合作店家信息.xlsx', '城东店', '10-single-inspect');

    const finalList = await listDocuments(page);
    expect(finalList.items.filter((item) => item.name === 'D02_合作店家信息.xlsx')).toHaveLength(1);
    await writeEvidence('single-upload-regression', {
      document_id: receipts[0].document.id,
      name: detail.document.name,
      job_state: detail.jobs[0]?.state,
      preview_total: preview.total,
      total_documents: finalList.total,
    });
    await shot(page, '11-single-published');
    expectLoopbackOnly(requests);
  });
});
