import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test, type Page } from '@playwright/test';

/**
 * T305 知识资产页 A1-A10（桌面 + 移动双 project）。
 * 数据来自 operations-assets-seed.py 的隔离种子；全部只读，不写库、不发问答 POST。
 */

interface VersionSeed {
  number: number;
  version_id: string;
  state: string;
}

interface CitationSeed {
  final_citations: number;
  related_requests: number;
  current_version: { number: number; state: string } | null;
}

interface CoreDocument {
  document_id: string;
  name: string;
  file_type: string;
  versions?: VersionSeed[];
  active_version_id?: string | null;
  import?: { state: string; stage: string; error_code: string; message: string };
  citations?: Record<'today' | '7d' | '30d', CitationSeed>;
}

interface Summary {
  dates: { today: string; yesterday: string; ten_days_ago: string; empty_since: string; empty_until: string };
  accounts: { admin: { username: string; password: string }; employee: { username: string; password: string } };
  documents: Record<string, CoreDocument>;
  totals: {
    documents: number;
    pages: number;
    page_size: number;
    review_total: number;
    failed_total: number;
    filler_documents: number;
  };
}

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SUMMARY_PATH = path.resolve(
  HERE,
  '..',
  '..',
  'docs',
  'reports',
  'OBS-EVAL',
  'P3',
  'T305-evidence',
  'isolated-var',
  'seed-summary.json',
);

const summary: Summary = JSON.parse(fs.readFileSync(SUMMARY_PATH, 'utf8'));
const CORE = summary.documents;

async function login(page: Page, role: 'admin' | 'employee'): Promise<void> {
  const account = summary.accounts[role];
  await page.goto('/login');
  await expect(page.getByRole('heading', { name: '登录', exact: true })).toBeVisible();
  await expect(page.getByLabel('账号')).toBeEditable();
  await page.getByLabel('账号').fill(account.username);
  await page.getByLabel('密码').fill(account.password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page).toHaveURL(/\/chat$/);
}

async function openAssets(page: Page, search = 'window=7d'): Promise<void> {
  await login(page, 'admin');
  await page.goto(`/operations/documents?${search}`);
  await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();
}

function rowByName(page: Page, name: string) {
  return page.locator(`[data-testid="ops-asset-row"][data-name="${name}"]`);
}

function query(url: string): URLSearchParams {
  return new URL(url).searchParams;
}

async function revealAllRows(page: Page): Promise<void> {
  const rows = page.getByTestId('ops-asset-row');
  let guard = 0;
  while (await page.getByTestId('ops-load-more').isVisible()) {
    await page.getByTestId('ops-load-more').click();
    guard += 1;
    if (guard > 10) break;
  }
  await expect(rows).toHaveCount(summary.totals.documents);
}

test.describe('T305 知识资产页 A1-A10', () => {
  test('A1 列表七列、>1 页与游标累计总数', async ({ page }) => {
    await openAssets(page);
    await expect(page.getByTestId('ops-placeholder-total')).toHaveText(String(summary.totals.documents));
    await expect(page.getByTestId('ops-placeholder-window')).toContainText('近 7 天');
    await expect(page.locator('.ops-compat-bar')).toContainText(`累计 ${summary.totals.pages} 页`);
    await expect(page.locator('.asset-table thead th')).toHaveCount(7);

    await expect(page.getByTestId('ops-asset-row')).toHaveCount(10);
    await page.getByTestId('ops-load-more').click();
    await expect(page.getByTestId('ops-asset-row')).toHaveCount(20);
    await revealAllRows(page);

    const price = rowByName(page, CORE.price.name);
    await expect(price.getByTestId('ops-asset-type')).toHaveText('Excel');
    await expect(price.getByTestId('ops-asset-current')).toHaveText('V1 生效');
    await expect(price.getByTestId('ops-asset-new')).toHaveText('无新版');
    await expect(price.getByTestId('ops-asset-citations')).toHaveText(
      String(CORE.price.citations?.['7d'].final_citations),
    );
    await expect(price.getByTestId('ops-asset-published')).toContainText(summary.dates.today);

    const launch = rowByName(page, CORE.launch.name);
    await expect(launch.getByTestId('ops-asset-current')).toHaveText('暂无生效版本');
    await expect(launch.getByTestId('ops-asset-new')).toHaveText('V1 待审核');

    const notice = rowByName(page, CORE.notice.name);
    await expect(notice.getByTestId('ops-asset-current')).toHaveText('V1 生效');
    await expect(notice.getByTestId('ops-asset-new')).toHaveText('V2 导入失败');
  });

  test('A2 文件类型 + 处理状态 + 名称组合筛选与重置', async ({ page }) => {
    await openAssets(page);
    await page.getByTestId('ops-type-select').selectOption('docx');

    const request = page.waitForRequest(
      (req) =>
        req.url().includes('/api/v1/operations/documents') && req.url().includes('version_state=review_required'),
    );
    await page.getByTestId('ops-state-select').selectOption('review_required');
    await request;
    await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();

    expect(query(page.url()).get('state')).toBe('review_required');
    await expect(page.getByTestId('ops-placeholder-total')).toHaveText('1');
    await expect(page.getByTestId('ops-asset-row')).toHaveCount(1);
    await expect(rowByName(page, CORE.material.name)).toBeVisible();
    await expect(page.getByTestId('ops-placeholder-state')).toContainText('version_state=review_required');

    await page.getByTestId('ops-name-search').fill('物料');
    await expect(page.getByTestId('ops-filter-total')).toContainText('共 1 份资料');

    await page.getByTestId('ops-name-search').fill('不存在的资料XYZ');
    await expect(page.getByTestId('ops-assets-empty')).toBeVisible();
    await page.getByTestId('ops-assets-empty').getByRole('button', { name: '清除筛选' }).click();
    await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();
    await expect(page.getByTestId('ops-placeholder-total')).toHaveText(String(summary.totals.documents));
    await expect(page.getByTestId('ops-asset-row')).toHaveCount(10);
  });

  test('A3 引用计数窗口切换与表脚口径一致', async ({ page }) => {
    await openAssets(page);
    await page.getByTestId('ops-name-search').fill(CORE.price.name);
    await expect(page.getByTestId('ops-asset-row')).toHaveCount(1);
    const price = rowByName(page, CORE.price.name);
    await expect(price.getByTestId('ops-asset-citations')).toHaveText(
      String(CORE.price.citations?.['7d'].final_citations),
    );

    await page.locator('[data-asset-window="30d"]').click();
    expect(query(page.url()).get('window')).toBe('30d');
    await expect(page.getByTestId('ops-window-label')).toContainText('近 30 天');
    await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();
    await expect(rowByName(page, CORE.price.name).getByTestId('ops-asset-citations')).toHaveText(
      String(CORE.price.citations?.['30d'].final_citations),
    );

    await page.locator('[data-asset-window="today"]').click();
    expect(query(page.url()).get('window')).toBe('today');
    await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();
    await expect(rowByName(page, CORE.price.name).getByTestId('ops-asset-citations')).toHaveText(
      String(CORE.price.citations?.today.final_citations),
    );

    await page.locator('[data-asset-window="7d"]').click();
    await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();
    await expect(rowByName(page, CORE.price.name).getByTestId('ops-asset-citations')).toHaveText(
      String(CORE.price.citations?.['7d'].final_citations),
    );
  });

  test('A4 最终引用去重与相关问答含冲突口径', async ({ page }) => {
    await openAssets(page);
    await page.getByTestId('ops-name-search').fill(CORE.price.name);
    await rowByName(page, CORE.price.name).click();
    await expect(page.getByTestId('ops-asset-drawer')).toBeVisible();
    await expect(page.getByTestId('ops-drawer-title')).toHaveText(CORE.price.name);

    const citation = CORE.price.citations?.['7d'];
    await expect(page.getByTestId('ops-ref-count')).toHaveText(String(citation?.final_citations));
    await expect(page.getByTestId('ops-related-count')).toContainText(`相关问答 ${citation?.related_requests} 条`);
    await expect(page.getByTestId('ops-related-count')).toContainText('含冲突关联');
    await expect(page.getByTestId('ops-related-count')).toContainText('不计入最终引用');
    expect(citation?.related_requests ?? 0).toBeGreaterThanOrEqual(citation?.final_citations ?? 0);
  });

  test('A5 版本列表历史行不展示新版本内容', async ({ page }) => {
    await openAssets(page);
    await page.getByTestId('ops-name-search').fill(CORE.flow.name);
    const row = rowByName(page, CORE.flow.name);
    await expect(row.getByTestId('ops-asset-current')).toHaveText('V2 生效');
    await row.click();
    await expect(page.getByTestId('ops-asset-drawer')).toBeVisible();
    await expect(page.getByTestId('ops-drawer-meta')).toContainText('2 个版本');
    await expect(page.getByTestId('ops-drawer-meta')).toContainText('当前生效 V2');

    await expect(page.getByTestId('ops-version-row')).toHaveCount(2);
    const oldVersion = page.locator('[data-testid="ops-version-row"][data-version-number="1"]');
    await expect(oldVersion).toHaveAttribute('data-version-state', 'superseded');
    await expect(oldVersion).toContainText('已替换');
    await expect(oldVersion).not.toContainText('当前生效');
    const newVersion = page.locator('[data-testid="ops-version-row"][data-version-number="2"]');
    await expect(newVersion).toHaveAttribute('data-version-state', 'published');
    await expect(newVersion).toContainText('当前生效');

    await expect(page.getByTestId('ops-asset-drawer').getByRole('button', { name: /上传|发布|删除|审核/ })).toHaveCount(0);
  });

  test('A6 待审核横幅、筛选与关闭旧版说明', async ({ page }) => {
    await login(page, 'admin');
    await page.goto('/operations/documents?state=review_required&window=7d');
    await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();

    await expect(page.getByTestId('ops-review-banner')).toBeVisible();
    await expect(page.getByTestId('ops-review-banner-count')).toHaveText(String(summary.totals.review_total));
    await expect(page.getByTestId('ops-review-banner')).toContainText('待审核');
    await expect(page.getByTestId('ops-placeholder-total')).toHaveText(String(summary.totals.review_total));
    await expect(page.getByTestId('ops-asset-row')).toHaveCount(summary.totals.review_total);
    await expect(page.getByTestId('ops-review-banner')).toContainText('继续生效');

    await expect(rowByName(page, CORE.launch.name).getByTestId('ops-asset-current')).toHaveText('暂无生效版本');
    await expect(rowByName(page, CORE.material.name).getByTestId('ops-asset-new')).toHaveText('V2 待审核');

    await page.getByTestId('ops-type-select').selectOption('xlsx');
    await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();
    await expect(page.getByTestId('ops-review-banner')).toHaveCount(0);
    await expect(page.getByTestId('ops-assets-empty')).toBeVisible();
    expect(query(page.url()).get('state')).toBe('review_required');
  });

  test('A7 导入失败红色状态与失败环节/错误码/继续生效', async ({ page }) => {
    const notice = CORE.notice;
    await login(page, 'admin');
    await page.goto(`/operations/documents?document_id=${notice.document_id}&state=failed&window=7d`);
    await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();

    await expect(page.getByTestId('ops-placeholder-total')).toHaveText('1');
    await expect(page.getByTestId('ops-placeholder-document')).toHaveText(notice.document_id);
    await expect(page.getByTestId('ops-asset-drawer')).toBeVisible();
    await expect(page.getByTestId('ops-drawer-title')).toHaveText(notice.name);
    await expect(page.getByTestId('ops-asset-drawer')).toHaveCount(1);

    await expect(page.getByTestId('ops-import-status')).toHaveAttribute('data-tone', 'failed');
    await expect(page.getByTestId('ops-import-headline')).toContainText('V2 导入失败，V1 继续生效');
    await expect(page.getByTestId('ops-import-stage')).toHaveText('文字识别');
    await expect(page.getByTestId('ops-import-error')).toHaveText('PARSE_INCOMPLETE');

    const row = rowByName(page, notice.name);
    await expect(row.getByTestId('ops-asset-current')).toHaveText('V1 生效');
    await expect(row.getByTestId('ops-asset-new')).toHaveText('V2 导入失败');
  });

  test('A8 抽屉 URL 直链、Esc 关闭与下钻链接', async ({ page }) => {
    await openAssets(page);
    await page.getByTestId('ops-name-search').fill(CORE.price.name);
    await rowByName(page, CORE.price.name).click();
    await expect(page.getByTestId('ops-asset-drawer')).toBeVisible();
    expect(query(page.url()).get('document_id')).toBe(CORE.price.document_id);

    const refHref = await page.getByTestId('ops-ref-link').getAttribute('href');
    expect(refHref).toContain('/operations/requests?');
    expect(refHref).toContain(`document_id=${CORE.price.document_id}`);
    expect(refHref).toContain('window=7d');
    expect(await page.getByTestId('ops-doc-link').getAttribute('href')).toBe('/documents');

    await page.reload();
    await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();
    await expect(page.getByTestId('ops-asset-drawer')).toBeVisible();
    await expect(page.getByTestId('ops-drawer-title')).toHaveText(CORE.price.name);

    await page.keyboard.press('Escape');
    await expect(page.getByTestId('ops-asset-drawer')).toHaveCount(0);
    expect(query(page.url()).get('document_id')).toBeNull();
    expect(query(page.url()).get('window')).toBe('7d');
  });

  test('A9 员工门禁、接口 500 重试与空态', async ({ page }) => {
    await login(page, 'employee');
    await page.goto('/operations/documents?window=7d');
    await expect(page.getByText('知识运营仅限管理员')).toBeVisible();
    await expect(page.getByTestId('ops-asset-row')).toHaveCount(0);

    const forbidden = await page.request.get('/api/v1/operations/documents?window=7d');
    expect(forbidden.status()).toBe(403);

    await page.context().clearCookies();
    await login(page, 'admin');

    const listPattern = /\/api\/v1\/operations\/documents(\?.*)?$/;
    await page.route(listPattern, (route) =>
      route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'boom' }) }),
    );
    await page.goto('/operations/documents?window=7d');
    await expect(page.getByTestId('ops-assets-error')).toBeVisible();
    await expect(page.getByTestId('ops-placeholder-ready')).toHaveCount(0);

    await page.unroute(listPattern);
    await page.getByTestId('ops-assets-retry').click();
    await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();
    await expect(page.getByTestId('ops-placeholder-total')).toHaveText(String(summary.totals.documents));

    await page.getByTestId('ops-name-search').fill('不存在的资料XYZ');
    await expect(page.getByTestId('ops-assets-empty')).toBeVisible();
    await page.getByTestId('ops-assets-empty').getByRole('button', { name: '清除筛选' }).click();
    await expect(page.getByTestId('ops-asset-row')).toHaveCount(10);
  });

  test('A10 移动端筛选/抽屉/只读无处理按钮', async ({ page }) => {
    await openAssets(page);
    await expect(page.getByRole('navigation', { name: '运营工作台页面' }).getByRole('link')).toHaveCount(3);

    await page.getByTestId('ops-type-select').selectOption('pdf');
    await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();
    await expect(page.getByTestId('ops-asset-row')).toHaveCount(2);

    await page.locator('[data-asset-window="30d"]').click();
    expect(query(page.url()).get('window')).toBe('30d');
    await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();

    await page.getByTestId('ops-asset-row').first().click();
    await expect(page.getByTestId('ops-asset-drawer')).toBeVisible();
    const box = await page.locator('.asset-drawer').boundingBox();
    const viewport = page.viewportSize() ?? { width: 390, height: 844 };
    expect(box?.width ?? 0).toBeLessThanOrEqual(Math.min(520, viewport.width));

    await expect(page.locator('button').filter({ hasText: /上传|发布|删除|审核|重试/ })).toHaveCount(0);
    await expect(page.getByText('只读', { exact: true }).first()).toBeVisible();

    await page.getByTestId('ops-drawer-close').click();
    await expect(page.getByTestId('ops-asset-drawer')).toHaveCount(0);
    expect(query(page.url()).get('document_id')).toBeNull();
    expect(query(page.url()).get('window')).toBe('30d');
  });
});
