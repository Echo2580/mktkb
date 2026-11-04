import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test, expect, type Locator, type Page, type Route } from '@playwright/test';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const FIXTURES = path.resolve(HERE, '../../fixtures/acceptance/normal');

function receipt(name: string, number = 1) {
  return {
    document: { id: `doc-${name}`, name, file_type: 'pdf', deleted: false },
    version: { id: `version-${name}`, number, state: 'queued' },
    job: { id: `job-${name}`, state: 'queued' },
  };
}

function errorBody(code: string, message: string, details: Record<string, unknown> | null = null) {
  return { error: { code, message, retryable: false, details } };
}

interface UploadCall {
  route: Route;
  name: string;
  allowSameName: boolean;
  replaceDocumentId: string | null;
  raw: string;
}

type UploadHandler = (call: UploadCall) => Promise<void> | void;

interface MockInfo {
  requests: string[];
}

function filenameFromMultipart(raw: string): string {
  return /Content-Disposition: form-data; name="file"; filename="([^"]*)"/i.exec(raw)?.[1] ?? '';
}

function externalUrls(urls: string[]): string[] {
  return urls.filter((url) => {
    try {
      const parsed = new URL(url);
      return !['127.0.0.1', 'localhost', '::1', '[::1]'].includes(parsed.hostname)
        && !['data:', 'blob:', 'about:'].includes(parsed.protocol);
    } catch {
      return false;
    }
  });
}

async function mockApp(page: Page, upload: UploadHandler): Promise<MockInfo> {
  const requests: string[] = [];
  page.on('request', (request) => requests.push(request.url()));

  await page.route('**/api/v1/**', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname.endsWith('/auth/me')) {
      await route.fulfill({
        json: {
          user: { id: 'admin', username: 'admin', display_name: '管理员', role: 'admin' },
          csrf_token: 'test-csrf',
        },
      });
      return;
    }
    if (request.method() === 'GET' && /\/(documents|conversations)$/.test(url.pathname)) {
      await route.fulfill({ json: { items: [], total: 0, offset: 0, limit: 20 } });
      return;
    }
    if (request.method() === 'POST' && url.pathname.endsWith('/documents')) {
      const raw = request.postDataBuffer()?.toString('utf8') ?? '';
      await upload({
        route,
        name: filenameFromMultipart(raw),
        allowSameName: raw.includes('name="allow_same_name"'),
        replaceDocumentId: null,
        raw,
      });
      return;
    }
    const replaceMatch = /\/documents\/([^/]+)\/versions$/.exec(url.pathname);
    if (request.method() === 'POST' && replaceMatch) {
      const raw = request.postDataBuffer()?.toString('utf8') ?? '';
      await upload({
        route,
        name: filenameFromMultipart(raw),
        allowSameName: false,
        replaceDocumentId: decodeURIComponent(replaceMatch[1]),
        raw,
      });
      return;
    }
    await route.abort();
    throw new Error(`Unexpected API request: ${request.method()} ${url.pathname}`);
  });

  await page.goto('/documents');
  return { requests };
}

async function chooseFolder(page: Page, folder: string) {
  await page.getByRole('button', { name: '上传文件夹', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: '上传文件夹' });
  await dialog.locator('input[type=file]').setInputFiles(folder);
  return dialog;
}

function rowFor(dialog: Locator, name: string) {
  return dialog.locator('.folder-upload-list li').filter({ hasText: name });
}

test('文件夹递归上传、跳过无效文件，按相对路径确定顺序登记任务', async ({ page }, info) => {
  const folder = info.outputPath('资料');
  await fs.mkdir(path.join(folder, '子目录'), { recursive: true });
  await fs.writeFile(path.join(folder, 'a.docx'), 'document');
  await fs.writeFile(path.join(folder, '子目录/b.pdf'), 'pdf');
  await fs.writeFile(path.join(folder, '说明.txt'), 'unsupported');
  await fs.writeFile(path.join(folder, '空文件.xlsx'), '');
  const uploaded: string[] = [];
  const { requests } = await mockApp(page, async (call) => {
    uploaded.push(call.name);
    await call.route.fulfill({ status: 202, json: receipt(call.name) });
  });

  const dialog = await chooseFolder(page, folder);
  await expect(dialog).toContainText('待上传 2');
  await expect(dialog).toContainText('已跳过 2');
  await expect(dialog).toContainText('子目录/b.pdf');
  await dialog.getByRole('button', { name: '开始上传', exact: true }).click();
  await expect(dialog).toContainText('已上传 2');

  // Chromium 目录选择时 multipart filename 可能带相对路径；产品必须只发送叶子名。
  expect(uploaded).toEqual(['a.docx', 'b.pdf']);
  const registry = await page.evaluate(() => JSON.parse(sessionStorage.getItem('mktkb.t08.job-registry.v1') ?? '{}'));
  expect(registry['version-a.docx']).toBe('job-a.docx');
  expect(registry['version-b.pdf']).toBe('job-b.pdf');
  expect(externalUrls(requests)).toEqual([]);
  await page.screenshot({ path: info.outputPath('folder-complete.png'), fullPage: true });
});

test('单文件失败继续，重试只上传失败项，重复内容跳过', async ({ page }, info) => {
  const folder = info.outputPath('资料');
  await fs.mkdir(folder, { recursive: true });
  for (const name of ['a.pdf', 'b.pdf', 'c.pdf']) await fs.writeFile(path.join(folder, name), name);
  const uploaded: string[] = [];
  const attempts: Record<string, number> = {};
  const { requests } = await mockApp(page, async (call) => {
    uploaded.push(call.name);
    attempts[call.name] = (attempts[call.name] ?? 0) + 1;
    if (call.name === 'a.pdf' && attempts[call.name] === 1) {
      await call.route.fulfill({ status: 500, json: errorBody('INTERNAL_ERROR', '处理失败') });
    } else if (call.name === 'b.pdf') {
      await call.route.fulfill({ status: 409, json: errorBody('DUPLICATE_CONTENT', '内容重复') });
    } else {
      await call.route.fulfill({ status: 202, json: receipt(call.name) });
    }
  });

  const dialog = await chooseFolder(page, folder);
  await dialog.getByRole('button', { name: '开始上传', exact: true }).click();
  await expect(dialog).toContainText('失败 1');
  await expect(dialog).toContainText('已上传 1');
  await expect(dialog).toContainText('已跳过 1');
  await dialog.getByRole('button', { name: '重试失败文件', exact: true }).click();
  await expect(dialog).toContainText('已上传 2');
  await expect(dialog).toContainText('失败 0');
  expect(uploaded).toEqual(['a.pdf', 'b.pdf', 'c.pdf', 'a.pdf']);
  expect(externalUrls(requests)).toEqual([]);
  await page.screenshot({ path: info.outputPath('folder-retry.png'), fullPage: true });
});

test('同名冲突可取消返回队列，并支持显式新增或替换', async ({ page }, info) => {
  const folder = info.outputPath('资料');
  await fs.mkdir(folder, { recursive: true });
  await fs.writeFile(path.join(folder, 'same.pdf'), 'same-name new bytes');
  await fs.writeFile(path.join(folder, 'replace.pdf'), 'replace bytes');
  const calls: string[] = [];
  const replaced: string[] = [];
  const { requests } = await mockApp(page, async (call) => {
    calls.push(`${call.replaceDocumentId ?? 'create'}:${call.name}`);
    if (call.replaceDocumentId) {
      replaced.push(`${call.replaceDocumentId}:${call.name}`);
      await call.route.fulfill({ status: 202, json: receipt(call.name, 2) });
      return;
    }
    if (call.allowSameName) {
      await call.route.fulfill({ status: 202, json: receipt(call.name) });
      return;
    }
    await call.route.fulfill({
      status: 409,
      json: errorBody('SAME_NAME_REQUIRES_ACTION', '需要选择', {
        candidates: [
          {
            id: `doc-${call.name}`,
            name: call.name,
            file_type: 'pdf',
            latest_version_number: 1,
            latest_state: 'published',
          },
        ],
      }),
    });
  });

  const dialog = await chooseFolder(page, folder);
  await dialog.getByRole('button', { name: '开始上传', exact: true }).click();
  await expect(dialog).toContainText('待确认 2');
  expect(calls).toHaveLength(2);

  // 打开同名处理但不上传就取消：返回队列，不静默新增或覆盖。
  await rowFor(dialog, 'same.pdf').getByRole('button', { name: '处理同名文件', exact: true }).click();
  const cancelDialog = page.getByRole('dialog', { name: '上传资料' });
  await expect(cancelDialog).toContainText('same.pdf');
  await cancelDialog.getByRole('button', { name: '取消', exact: true }).click();
  await expect(dialog).toContainText('待确认 2');
  expect(calls).toHaveLength(2);

  await rowFor(dialog, 'same.pdf').getByRole('button', { name: '处理同名文件', exact: true }).click();
  let nested = page.getByRole('dialog', { name: '上传资料' });
  await nested.getByRole('button', { name: '上传', exact: true }).click();
  await expect(nested).toContainText('已存在同名资料');
  await nested.getByRole('button', { name: '作为独立资料新增', exact: true }).click();
  await expect(rowFor(dialog, 'same.pdf')).toContainText('已上传，等待处理');

  await rowFor(dialog, 'replace.pdf').getByRole('button', { name: '处理同名文件', exact: true }).click();
  nested = page.getByRole('dialog', { name: '上传资料' });
  await nested.getByRole('button', { name: '上传', exact: true }).click();
  await expect(nested).toContainText('已存在同名资料');
  await nested.getByRole('button', { name: '替换此资料', exact: true }).click();
  await expect(rowFor(dialog, 'replace.pdf')).toContainText('已上传，等待处理');

  await expect(dialog).toContainText('已上传 2');
  expect(replaced).toEqual(['doc-replace.pdf:replace.pdf']);
  expect(externalUrls(requests)).toEqual([]);
  await page.screenshot({ path: info.outputPath('folder-same-name.png'), fullPage: true });
});

test('403 停止后续上传，登录状态恢复后可继续剩余项', async ({ page }, info) => {
  const folder = info.outputPath('资料');
  await fs.mkdir(folder, { recursive: true });
  for (const name of ['a.pdf', 'b.pdf', 'c.pdf']) await fs.writeFile(path.join(folder, name), name);
  const uploaded: string[] = [];
  let deny = true;
  const { requests } = await mockApp(page, async (call) => {
    uploaded.push(call.name);
    if (deny && call.name === 'a.pdf') {
      await call.route.fulfill({ status: 403, json: errorBody('FORBIDDEN', '没有资料管理权限') });
      return;
    }
    await call.route.fulfill({ status: 202, json: receipt(call.name) });
  });

  const dialog = await chooseFolder(page, folder);
  await dialog.getByRole('button', { name: '开始上传', exact: true }).click();
  await expect(dialog).toContainText('失败 1');
  await expect(dialog).toContainText('待上传 2');
  await expect(dialog).toContainText('已停止后续上传');
  expect(uploaded).toEqual(['a.pdf']);

  deny = false;
  await dialog.getByRole('button', { name: '重试失败文件', exact: true }).click();
  await expect(dialog).toContainText('已上传 1');
  await dialog.getByRole('button', { name: '继续上传', exact: true }).click();
  await expect(dialog).toContainText('已上传 3');
  expect(uploaded).toEqual(['a.pdf', 'a.pdf', 'b.pdf', 'c.pdf']);
  expect(externalUrls(requests)).toEqual([]);
  await page.screenshot({ path: info.outputPath('folder-403-stop.png'), fullPage: true });
});

test('401 停止后续上传并回到登录页', async ({ page }, info) => {
  const folder = info.outputPath('资料');
  await fs.mkdir(folder, { recursive: true });
  for (const name of ['a.pdf', 'b.pdf', 'c.pdf']) await fs.writeFile(path.join(folder, name), name);
  const uploaded: string[] = [];
  const { requests } = await mockApp(page, async (call) => {
    uploaded.push(call.name);
    await call.route.fulfill({ status: 401, json: errorBody('AUTH_REQUIRED', '登录状态已失效') });
  });

  const dialog = await chooseFolder(page, folder);
  await dialog.getByRole('button', { name: '开始上传', exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole('heading', { name: '登录', exact: true })).toBeVisible();
  expect(uploaded).toEqual(['a.pdf']);
  expect(externalUrls(requests)).toEqual([]);
  await page.screenshot({ path: info.outputPath('folder-401-stop.png'), fullPage: true });
});

test('停止后续上传会等待当前文件收尾，再可继续剩余项', async ({ page }, info) => {
  const folder = info.outputPath('资料');
  await fs.mkdir(folder, { recursive: true });
  for (const name of ['a.pdf', 'b.pdf', 'c.pdf']) await fs.writeFile(path.join(folder, name), name);
  const uploaded: string[] = [];
  const { requests } = await mockApp(page, async (call) => {
    uploaded.push(call.name);
    if (call.name === 'a.pdf' && uploaded.length === 1) {
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }
    await call.route.fulfill({ status: 202, json: receipt(call.name) });
  });

  const dialog = await chooseFolder(page, folder);
  await dialog.getByRole('button', { name: '开始上传', exact: true }).click();
  await expect(dialog).toContainText('正在上传');
  await dialog.getByRole('button', { name: '停止后续上传', exact: true }).click();
  await expect(dialog.getByRole('button', { name: '等待当前文件完成…', exact: true })).toBeVisible();
  await expect(dialog).toContainText('已上传 1');
  await expect(dialog).toContainText('待上传 2');
  expect(uploaded).toEqual(['a.pdf']);

  await dialog.getByRole('button', { name: '继续上传', exact: true }).click();
  await expect(dialog).toContainText('已上传 3');
  expect(uploaded).toEqual(['a.pdf', 'b.pdf', 'c.pdf']);
  expect(externalUrls(requests)).toEqual([]);
  await page.screenshot({ path: info.outputPath('folder-stop.png'), fullPage: true });
});

test('图片文件可进入文件夹队列（Mock，不代表真实 OCR 通过）', async ({ page }, info) => {
  const folder = info.outputPath('资料');
  await fs.mkdir(folder, { recursive: true });
  await fs.copyFile(path.join(FIXTURES, 'D09_物料领用通知.png'), path.join(folder, '通知.png'));
  await fs.copyFile(path.join(FIXTURES, 'D10_盘点通知.jpg'), path.join(folder, '盘点.jpg'));
  const uploaded: string[] = [];
  const { requests } = await mockApp(page, async (call) => {
    uploaded.push(call.name);
    await call.route.fulfill({ status: 202, json: receipt(call.name) });
  });

  const dialog = await chooseFolder(page, folder);
  await expect(dialog).toContainText('待上传 2');
  await dialog.getByRole('button', { name: '开始上传', exact: true }).click();
  await expect(dialog).toContainText('已上传 2');
  expect(uploaded.sort()).toEqual(['盘点.jpg', '通知.png'].sort());
  expect(externalUrls(requests)).toEqual([]);
  await page.screenshot({ path: info.outputPath('folder-images-mock.png'), fullPage: true });
});
