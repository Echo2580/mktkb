import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test, type Page } from '@playwright/test';

/**
 * T306 集成验收 I1-I8（desktop 1440×900 + mobile 390×844）。
 * 数据来自 operations-integration-seed.py 的同一套受控种子；
 * 期望值全部读 seed-summary.json，不手抄接口数据；不发问答 POST、不发起评测。
 */

interface Metrics {
  completed: number;
  not_found: number;
  conflict: number;
  review: number;
  interrupted: number;
  active_documents: number;
  pending: number;
  trend: Array<{ date: string; completed: number; citations: number }>;
  distribution: Record<string, number>;
  trace_status: string;
}

interface Citation {
  document_id: string;
  version_number: number | null;
  document_name: string | null;
  status: string;
}

interface ConflictEntry {
  value: string;
  document_name: string | null;
  version_number: number | null;
  status: string | null;
}

interface Summary {
  main_base: string;
  trace_off_base: string;
  dates: { today: string; yesterday: string; ten_days_ago: string; empty_since: string; empty_until: string };
  accounts: { admin: { username: string; password: string }; employee: { username: string; password: string } };
  request_ids: Record<string, string>;
  metrics: { week7d: Metrics; today: Metrics; yesterday: Metrics; month30d: Metrics; empty: Metrics };
  requests: { today: number; week7d: number; conflict_week: number; notice_document: number };
  documents_count: { week7d: number; failed: number; review: number };
  detail: {
    answer_multi: {
      question: string;
      result_kind: string;
      citation_count: number;
      citation: Citation;
      trace_status: string;
    };
    conflict: { question: string; citation_count: number; conflicts: Array<{ field: string; entries: ConflictEntry[] }> };
    notice: {
      document_id: string;
      name: string;
      versions: Array<{ number: number; version_id: string; state: string }>;
      import_error_code: string;
      import_stage: string;
      related_requests_count: number;
      failed_total: number;
    };
    manual: { document_id: string; name: string; active_version_number: number | null };
    launch: { document_id: string; name: string; review_state: string };
  };
  eval: {
    run_ids: string[];
    skipped_dirs: string[];
    api_status: string;
    api_skipped: number;
    runs: Record<
      string,
      { case_count: number; holdout_detected: boolean; details_withheld: boolean; scored_count: number; error_count: number; expected_status: string }
    >;
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
  'T306-evidence',
  'isolated-var',
  'seed-summary.json',
);
const summary: Summary = JSON.parse(fs.readFileSync(SUMMARY_PATH, 'utf8'));

function query(url: string): URLSearchParams {
  return new URL(url).searchParams;
}

async function login(page: Page, role: 'admin' | 'employee', base = ''): Promise<void> {
  const account = summary.accounts[role];
  await page.goto(`${base}/login`);
  await expect(page.getByRole('heading', { name: '登录', exact: true })).toBeVisible();
  await page.getByLabel('账号').fill(account.username);
  await page.getByLabel('密码').fill(account.password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page).toHaveURL(/\/chat$/);
}

async function openOverview(page: Page): Promise<void> {
  await login(page, 'admin');
  await page.goto('/operations');
  await expect(page.getByTestId('ops-ready')).toBeVisible();
}

test.describe('T306 集成验收 I1-I8', () => {
  test('I1 首页→趋势日期→问答明细：总数==该日完成量，抽屉内容与种子一致', async ({ page }) => {
    await openOverview(page);
    const week = summary.metrics.week7d;
    await expect(page.getByTestId('ops-metric-completed')).toHaveText(String(week.completed));

    const lastDay = week.trend[week.trend.length - 1];
    expect(lastDay.date).toBe(summary.dates.today);
    await page.locator(`[data-trend-date="${lastDay.date}"]`).click();
    await expect(page).toHaveURL(/\/operations\/requests/);
    const search = query(page.url());
    expect(search.get('since')).toBe(lastDay.date);
    expect(search.get('until')).toBe(lastDay.date);
    expect(search.get('window')).toBe('custom');
    await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();
    await expect(page.getByTestId('ops-placeholder-total')).toHaveText(String(summary.metrics.today.completed));
    expect(lastDay.completed).toBe(summary.metrics.today.completed);
    expect(summary.requests.today).toBe(summary.metrics.today.completed);

    const answer = summary.detail.answer_multi;
    await page.locator(`[data-request-id="${summary.request_ids.answer_multi}"]`).click();
    await expect(page.getByTestId('qa-drawer')).toBeVisible();
    await expect(page.getByTestId('qa-question')).toContainText(answer.question);
    await expect(page.getByTestId('qa-result-badge')).toHaveText('已回答');
    await expect(page.getByTestId('qa-citations')).toContainText(`本回答最终引用 ${answer.citation_count} 份资料`);
    const card = page.locator(`[data-citation="${answer.citation.document_id}"]`);
    await expect(card).toContainText(answer.citation.document_name ?? '');
    await expect(card).toContainText(`V${answer.citation.version_number}`);
    await expect(card).toContainText('当前有效');
  });

  test('I2 结果分布→冲突详情→核对版本：两方均 active、值/名称/版本一致、引用数 0', async ({ page }) => {
    await openOverview(page);
    await page.locator('.ops-keyboard-list [data-kind="conflict"]').click();
    await expect(page).toHaveURL(/\/operations\/requests/);
    expect(query(page.url()).get('kind')).toBe('conflict');
    expect(query(page.url()).get('window')).toBe('7d');
    await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();
    await expect(page.getByTestId('ops-placeholder-total')).toHaveText(String(summary.requests.conflict_week));

    const conflicts = summary.detail.conflict;
    await page.locator(`[data-request-id="${summary.request_ids.conflict}"]`).click();
    await expect(page.getByTestId('qa-drawer')).toBeVisible();
    await expect(page.getByTestId('qa-question')).toContainText(conflicts.question);
    await expect(page.getByTestId('qa-result-badge')).toHaveText('资料冲突');
    const entries = page.locator('[data-conflict-entry]');
    await expect(entries).toHaveCount(conflicts.conflicts[0].entries.length);
    for (const [index, entry] of conflicts.conflicts[0].entries.entries()) {
      const card = entries.nth(index);
      await expect(card).toContainText(entry.document_name ?? '');
      await expect(card).toContainText(entry.value);
      await expect(card).toContainText(`V${entry.version_number}`);
      await expect(card).toContainText('当前有效');
      expect(entry.status).toBe('active');
    }
    await expect(page.getByTestId('qa-citations')).toHaveCount(0);
    expect(conflicts.citation_count).toBe(0);

    const manual = summary.detail.manual;
    await page.goto(`/operations/documents?document_id=${manual.document_id}&window=7d`);
    await expect(page.getByTestId('ops-asset-drawer')).toBeVisible();
    await expect(page.getByTestId('ops-drawer-title')).toHaveText(manual.name);
    const activeVersion = page.locator(
      `[data-testid="ops-version-row"][data-version-number="${manual.active_version_number}"]`,
    );
    await expect(activeVersion).toHaveAttribute('data-version-state', 'published');
    await expect(activeVersion).toContainText('当前生效');
  });

  test('I3 待处理→导入失败详情→关联问答：参数、失败块与 T304↔T305 串联', async ({ page }) => {
    await openOverview(page);
    await page.locator('[data-pending-import]').first().click();
    await expect(page).toHaveURL(/\/operations\/documents/);
    const search = query(page.url());
    const notice = summary.detail.notice;
    expect(search.get('document_id')).toBe(notice.document_id);
    expect(search.get('state')).toBe('failed');
    await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();
    await expect(page.getByTestId('ops-placeholder-total')).toHaveText(String(notice.failed_total));
    await expect(page.getByTestId('ops-asset-drawer')).toBeVisible();
    await expect(page.getByTestId('ops-drawer-title')).toHaveText(notice.name);
    await expect(page.getByTestId('ops-import-headline')).toContainText('V2 导入失败，V1 继续生效');
    await expect(page.getByTestId('ops-import-error')).toHaveText(notice.import_error_code);

    await page.getByTestId('ops-ref-link').click();
    await expect(page).toHaveURL(/\/operations\/requests/);
    expect(query(page.url()).get('document_id')).toBe(notice.document_id);
    await expect(page.getByTestId('qa-asset-banner')).toBeVisible();
    await expect(page.getByTestId('qa-asset-banner')).toContainText('已按资料筛选问答记录');
    await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();
    await expect(page.getByTestId('ops-placeholder-total')).toHaveText(String(notice.related_requests_count));
    expect(notice.related_requests_count).toBe(summary.requests.notice_document);
  });

  test('I4 员工门禁：三页文案 + 五个接口 403', async ({ page }) => {
    await login(page, 'employee');
    const nav = page.getByRole('navigation', { name: '主要导航' });
    if (page.viewportSize()!.width < 600) await page.getByRole('button', { name: '打开菜单' }).click();
    await expect(nav.getByRole('link', { name: '知识运营' })).toHaveCount(0);

    const pages = ['/operations', '/operations/requests?window=7d', '/operations/documents?window=7d'];
    for (const target of pages) {
      await page.goto(target);
      await expect(page.getByText('知识运营仅限管理员')).toBeVisible();
    }

    const endpoints = [
      '/api/v1/operations/overview?window=7d',
      '/api/v1/operations/requests?window=7d',
      '/api/v1/operations/documents?window=7d',
      `/api/v1/operations/requests/${summary.request_ids.answer_multi}`,
      `/api/v1/operations/documents/${summary.detail.notice.document_id}`,
      '/api/v1/operations/evaluation-runs',
    ];
    for (const endpoint of endpoints) {
      const response = await page.request.get(endpoint);
      expect(response.status()).toBe(403);
      const payload = await response.json();
      expect(payload.error.code).toBe('ROLE_REQUIRED');
    }
  });

  test('I5 Trace 关闭栈业务可读 + 主栈 not_recorded 文案', async ({ page }) => {
    const closed = summary.trace_off_base;
    await login(page, 'admin', closed);
    const answer = summary.detail.answer_multi;
    await page.goto(`${closed}/operations/requests?window=7d&request_id=${summary.request_ids.answer_multi}`);
    await expect(page.getByTestId('qa-drawer')).toBeVisible();
    expect(new URL(page.url()).port).toBe('5304');
    await expect(page.getByTestId('qa-question')).toContainText(answer.question);
    await expect(page.getByTestId('qa-result-badge')).toHaveText('已回答');
    await expect(page.locator(`[data-citation="${answer.citation.document_id}"]`)).toContainText('当前有效');
    await expect(page.getByTestId('qa-trace-state')).toContainText('Trace 已关闭');
    await expect(page.getByTestId('qa-stages')).toHaveCount(0);

    const conflicts = summary.detail.conflict;
    await page.goto(`${closed}/operations/requests?window=7d&kind=conflict`);
    await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();
    await page.locator(`[data-request-id="${summary.request_ids.conflict}"]`).click();
    await expect(page.getByTestId('qa-conflicts')).toBeVisible();
    const entries = page.locator('[data-conflict-entry]');
    await expect(entries).toHaveCount(conflicts.conflicts[0].entries.length);
    await expect(page.getByTestId('qa-trace-state')).toContainText('Trace 已关闭');

    await page.goto(`/operations/requests?window=7d&request_id=${summary.request_ids.no_trace}`);
    await expect(page.getByTestId('qa-drawer')).toBeVisible();
    await expect(page.getByTestId('qa-question')).toContainText('门店营业时间到几点');
    await expect(page.getByTestId('qa-trace-state')).toContainText('本次未记录执行过程');
    await expect(page.getByTestId('qa-stages')).toHaveCount(0);
  });

  test('I6 空窗口：总览计 0 无假百分比、requests 空态、assets 无伪造引用、评测空目录不出现', async ({ page }) => {
    await login(page, 'admin');
    await page.goto(`/operations?window=custom&since=${summary.dates.empty_since}&until=${summary.dates.empty_until}`);
    await expect(page.getByTestId('ops-ready')).toBeVisible();
    await expect(page.getByTestId('ops-metric-completed')).toHaveText('0');
    await expect(page.getByTestId('ops-metric-not_found')).toHaveText('0');
    await expect(page.getByTestId('ops-metric-conflict')).toHaveText('0');
    await expect(page.getByTestId('ops-trend-empty')).toBeVisible();
    await expect(page.getByTestId('ops-dist-empty')).toBeVisible();
    await expect(page.getByTestId('ops-chart-trend')).toHaveCount(0);
    await expect(page.getByTestId('ops-chart-distribution')).toHaveCount(0);
    await expect(page.locator('[data-pending-request]')).toHaveCount(0);
    const pageText = await page.locator('.page').innerText();
    expect(pageText).not.toContain('NaN');
    expect(pageText).not.toMatch(/\d+(\.\d+)?%/);

    await page.goto(
      `/operations/requests?window=custom&since=${summary.dates.empty_since}&until=${summary.dates.empty_until}`,
    );
    await expect(page.getByTestId('qa-empty')).toBeVisible();
    await expect(page.getByTestId('ops-placeholder-total')).toHaveText('0');

    await page.goto(
      `/operations/documents?window=custom&since=${summary.dates.empty_since}&until=${summary.dates.empty_until}`,
    );
    await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();
    // 资产列表为“当前库存”口径（T305 已定），空窗口仍列出 4 份资料，但引用必须全为 0，不得伪造。
    await expect(page.getByTestId('ops-filter-total')).toContainText('共 4 份资料');
    const citationCells = page.locator('.asset-ref-count');
    await expect(citationCells).toHaveCount(4);
    for (let index = 0; index < 4; index += 1) {
      await expect(citationCells.nth(index)).toHaveText('0');
    }
    // 空态由“无匹配筛选”触发：processing 版本 + 空窗口 → 0 份，展示空态而不是假数据。
    await page.goto(
      `/operations/documents?state=processing&window=custom&since=${summary.dates.empty_since}&until=${summary.dates.empty_until}`,
    );
    await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();
    await expect(page.getByTestId('ops-assets-empty')).toBeVisible();
    await expect(page.getByTestId('ops-filter-total')).toContainText('共 0 份资料');

    await page.goto('/operations/requests?window=7d&tab=eval');
    await expect(page.getByTestId('qa-eval-table')).toBeVisible();
    await expect(page.locator('[data-run-id]')).toHaveCount(summary.eval.run_ids.length);
    await expect(page.locator('.page')).not.toContainText(summary.eval.skipped_dirs[0]);
  });

  test('I7 移动端 390 完整走通 I3 一条链', async ({ page }, testInfo) => {
    if (testInfo.project.name === 'mobile') {
      expect(page.viewportSize()).toEqual({ width: 390, height: 844 });
    }
    await openOverview(page);
    await page.locator('[data-pending-import]').first().click();
    const notice = summary.detail.notice;
    expect(query(page.url()).get('document_id')).toBe(notice.document_id);
    await expect(page.getByTestId('ops-asset-drawer')).toBeVisible();
    await expect(page.getByTestId('ops-import-headline')).toContainText('V2 导入失败，V1 继续生效');
    await page.getByTestId('ops-ref-link').click();
    await expect(page.getByTestId('qa-asset-banner')).toBeVisible();
    await expect(page.getByTestId('ops-placeholder-total')).toHaveText(String(notice.related_requests_count));
  });

  test('I8 评测摘要：分母/状态与受控 run 一致、holdout 扣留、无发起入口', async ({ page }) => {
    await login(page, 'admin');
    await page.goto('/operations/requests?window=7d&tab=eval');
    await expect(page.getByTestId('qa-eval-table')).toBeVisible();
    const rows = page.locator('[data-run-id]');
    await expect(rows).toHaveCount(summary.eval.run_ids.length);

    for (const runId of summary.eval.run_ids) {
      const run = summary.eval.runs[runId];
      const row = page.locator(`[data-run-id="${runId}"]`);
      await expect(row.getByTestId('qa-eval-case-count')).toHaveText(String(run.case_count));
      await expect(row.getByTestId('qa-eval-status')).toHaveText(run.expected_status);
      if (run.details_withheld) await expect(row).toContainText('holdout 明细已扣留');
    }
    await expect(page.locator('[data-run-id="t306-eval-holdout-01"]')).toContainText('holdout');
    await expect(page.getByText('开始评测')).toHaveCount(0);
    await expect(page.getByText('重试评测')).toHaveCount(0);
    await expect(page.getByText('报告下载')).toHaveCount(0);

    await page.locator('[data-view-run="t306-eval-b0-01"]').click();
    await expect(page.getByTestId('qa-eval-drawer')).toBeVisible();
    await expect(page.getByTestId('qa-eval-drawer')).toContainText('0.86');
    await page.getByTestId('qa-eval-drawer-close').click();

    await page.locator('[data-view-run="t306-eval-holdout-01"]').click();
    await expect(page.getByTestId('qa-eval-drawer-withheld')).toContainText('仅聚合可见');
    await expect(page.getByTestId('qa-eval-drawer')).not.toContainText('leak-into-ui');
  });
});
