import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test, type Page } from '@playwright/test';

/**
 * T304 问答诊断 Q1-Q10。
 * 数据全部来自隔离目录的受控种子（operations-qa-seed.py 输出），
 * 期望值从 seed-summary.json 读取，不手抄接口数据；不发问答 POST、不发起评测。
 */

interface Citation {
  document_id: string;
  version_number: number | null;
  document_name: string | null;
  status: string;
  locator: Record<string, unknown> | null;
  published_at?: string | null;
}

interface Summary {
  frontend_base: string;
  trace_closed_base: string;
  dates: { today: string; yesterday: string; ten_days_ago: string; empty_since: string; empty_until: string };
  accounts: { admin: { username: string; password: string }; employee: { username: string; password: string } };
  request_ids: Record<string, string>;
  totals: {
    week7d: number;
    today: number;
    month30d: number;
    empty: number;
    conflict_week: number;
    page_size: number;
    first_page_rows: number;
    pages: number;
  };
  detail: {
    answer_multi: {
      citation_count: number;
      citation: Citation;
      trace_status: string;
      stage_labels: string[];
      stage_durations: Record<string, number>;
      attempts: number;
    };
    answer_superseded: { citation_count: number; citation: Citation; stage_labels: string[] };
    conflict: {
      citation_count: number;
      citations: Citation[];
      conflicts: Array<{ field: string; entries: Array<{ value: string; document_name: string; version_number: number; status: string }> }>;
    };
    service_error: { error_code: string; stages: string[] };
    no_trace: { trace_status: string; attempts: number };
    replayed: { attempts: Array<{ attempt: number; replayed: boolean; spans: number }> };
  };
  eval: {
    run_ids: string[];
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
  'T304-evidence',
  'isolated-var',
  'seed-summary.json',
);
const summary: Summary = JSON.parse(fs.readFileSync(SUMMARY_PATH, 'utf8'));

const MAIN_LABELS: Record<string, string> = {
  parse: '解析计划',
  recall: '检索召回',
  vector_recall: '向量召回',
  fuse: '融合排序',
  rerank: '重排',
  answer: '答案生成',
  commit: '状态持久化',
  intent_parse: '意图解析',
  retrieve: '证据检索',
  model_answer: '模型作答',
  answer_validate: '答案校验',
};

async function loginAt(page: Page, base = ''): Promise<void> {
  const account = summary.accounts.admin;
  await page.goto(`${base}/login`);
  await expect(page.getByRole('heading', { name: '登录', exact: true })).toBeVisible();
  await page.getByLabel('账号').fill(account.username);
  await page.getByLabel('密码').fill(account.password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page).toHaveURL(/\/chat$/);
}

async function loginEmployee(page: Page): Promise<void> {
  const account = summary.accounts.employee;
  await page.goto('/login');
  await page.getByLabel('账号').fill(account.username);
  await page.getByLabel('密码').fill(account.password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page).toHaveURL(/\/chat$/);
}

async function openRecords(page: Page, query: string): Promise<void> {
  await page.goto(`/operations/requests?${query}`);
  await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();
}

async function openDrawerById(page: Page, requestId: string, query = 'window=7d'): Promise<void> {
  await page.goto(`/operations/requests?${query}&request_id=${requestId}`);
  await expect(page.getByTestId('qa-drawer')).toBeVisible();
}

async function rowIds(page: Page): Promise<string[]> {
  return page.locator('[data-testid="qa-row"]').evaluateAll((rows) =>
    rows.map((row) => row.getAttribute('data-request-id') ?? ''),
  );
}

test.describe('T304 问答诊断', () => {
  test('Q1 窗口/结果筛选与重置：URL、总数、列表一致', async ({ page }) => {
    await loginAt(page);
    await openRecords(page, 'window=today');
    await expect(page.getByTestId('ops-placeholder-total')).toHaveText(String(summary.totals.today));
    await expect(page.getByTestId('ops-placeholder-kind')).toContainText('全部');

    await page.locator('[data-window-option="7d"]').click();
    await expect(page).toHaveURL(/window=7d/);
    await expect(page.getByTestId('ops-placeholder-total')).toHaveText(String(summary.totals.week7d));

    await page.getByTestId('qa-kind-filter').selectOption('conflict');
    await expect(page).toHaveURL(/kind=conflict/);
    await expect(page.getByTestId('qa-kind-filter')).toHaveValue('conflict');
    await expect(page.getByTestId('ops-placeholder-kind')).toContainText('conflict');
    await expect(page.getByTestId('ops-placeholder-total')).toHaveText(String(summary.totals.conflict_week));
    await expect(page.getByTestId('qa-row')).toHaveCount(summary.totals.conflict_week);
    await expect(page.getByTestId('qa-row').first()).toContainText('资料冲突');

    await page.getByTestId('qa-reset').click();
    await expect(page).not.toHaveURL(/kind=/);
    await expect(page.getByTestId('qa-kind-filter')).toHaveValue('');
    await expect(page.getByTestId('ops-placeholder-total')).toHaveText(String(summary.totals.week7d));
  });

  test('Q2 游标分页：首页 20 条、加载更多无重复、总数一致', async ({ page }) => {
    await loginAt(page);
    await openRecords(page, 'window=7d');
    await expect(page.getByTestId('ops-placeholder-total')).toHaveText(String(summary.totals.week7d));
    await expect(page.getByTestId('qa-row')).toHaveCount(summary.totals.first_page_rows);

    const first = await rowIds(page);
    await page.getByTestId('qa-load-more').click();
    await expect(page.getByTestId('qa-row')).toHaveCount(summary.totals.week7d);

    const all = await rowIds(page);
    expect(new Set(all).size).toBe(summary.totals.week7d);
    expect(all.slice(0, first.length)).toEqual(first);
    await expect(page.getByTestId('qa-list-complete')).toContainText(`全部 ${summary.totals.week7d} 条`);
    await expect(page.getByTestId('ops-placeholder-total')).toHaveText(String(summary.totals.week7d));
  });

  test('Q3 直链打开抽屉、Esc 关闭且保留筛选、键盘可打开', async ({ page }) => {
    await loginAt(page);
    await openDrawerById(page, summary.request_ids.answer_multi, 'window=7d&kind=answer');
    await expect(page.getByTestId('qa-question')).toContainText('A 套餐');
    await expect(page.getByTestId('qa-question-meta')).toContainText('请求标识');

    await page.keyboard.press('Escape');
    await expect(page.getByTestId('qa-drawer')).toHaveCount(0);
    const afterClose = new URL(page.url());
    expect(afterClose.searchParams.get('request_id')).toBeNull();
    expect(afterClose.searchParams.get('window')).toBe('7d');
    expect(afterClose.searchParams.get('kind')).toBe('answer');

    const row = page.locator(`[data-request-id="${summary.request_ids.answer_superseded}"]`);
    await row.focus();
    await page.keyboard.press('Enter');
    await expect(page.getByTestId('qa-drawer')).toBeVisible();
    await expect(page.getByTestId('qa-question')).toContainText('上一版');
    expect(new URL(page.url()).searchParams.get('request_id')).toBe(summary.request_ids.answer_superseded);
  });

  test('Q4 引用资料与版本：active 定位、superseded 仅元信息', async ({ page }) => {
    await loginAt(page);
    const multi = summary.detail.answer_multi;
    await openDrawerById(page, summary.request_ids.answer_multi);
    await expect(page.getByTestId('qa-result-badge')).toHaveText('已回答');
    await expect(page.getByTestId('qa-revision')).toHaveText('5');
    await expect(page.getByTestId('qa-citations')).toContainText(
      `本回答最终引用 ${multi.citation_count} 份资料`,
    );

    const card = page.locator(`[data-citation="${multi.citation.document_id}"]`);
    await expect(card).toContainText('门店产品价目表');
    await expect(card).toContainText(`V${multi.citation.version_number}`);
    await expect(card).toContainText('当前有效');
    await expect(card).toContainText('sheet Sheet1');
    await expect(card).not.toContainText('不应出口');

    const superseded = summary.detail.answer_superseded;
    await openDrawerById(page, summary.request_ids.answer_superseded);
    const oldCard = page.locator(`[data-citation="${superseded.citation.document_id}"]`);
    await expect(oldCard).toHaveAttribute('data-status', 'superseded');
    await expect(oldCard).toContainText('V1');
    await expect(oldCard).toContainText('已被替换');
    await expect(oldCard).not.toContainText('定位：');
    await expect(page.getByTestId('qa-revision')).toHaveText('3');
  });

  test('Q5 冲突两方均为当前有效版本，不显示引用', async ({ page }) => {
    await loginAt(page);
    const conflict = summary.detail.conflict;
    await openDrawerById(page, summary.request_ids.conflict);
    await expect(page.getByTestId('qa-result-badge')).toHaveText('资料冲突');
    await expect(page.getByTestId('qa-conflicts')).toContainText('记载不一致');
    await expect(page.getByTestId('qa-conflicts')).toContainText('建议处理');

    const entries = page.locator('[data-conflict-entry]');
    await expect(entries).toHaveCount(conflict.conflicts[0].entries.length);
    for (const [index, entry] of conflict.conflicts[0].entries.entries()) {
      const card = entries.nth(index);
      await expect(card).toContainText(entry.document_name);
      await expect(card).toContainText(entry.value);
      await expect(card).toContainText('当前有效');
    }
    await expect(page.getByTestId('qa-citations')).toHaveCount(0);
    await expect(page.getByTestId('qa-no-citations')).toHaveCount(0);
  });

  test('Q6 执行阶段条：冻结映射、按实际 Span、未记录不补、重放可见', async ({ page }) => {
    await loginAt(page);
    const multi = summary.detail.answer_multi;
    await openDrawerById(page, summary.request_ids.answer_multi);

    const stages = page.locator('[data-testid="qa-stages"] [data-stage]');
    await expect(stages).toHaveCount(multi.stage_labels.length);
    for (const [index, label] of multi.stage_labels.entries()) {
      await expect(stages.nth(index).locator('.qa-stage-label')).toHaveText(label);
    }
    for (const [spanName, ms] of Object.entries(multi.stage_durations)) {
      if (!(spanName in MAIN_LABELS)) continue;
      await expect(page.locator(`[data-stage="${spanName}"] .qa-stage-value`)).toHaveText(`${ms} ms`);
    }
    const recordedSum = Object.entries(multi.stage_durations)
      .filter(([name]) => name in MAIN_LABELS)
      .reduce((total, [, ms]) => total + ms, 0);
    await expect(page.getByTestId('qa-stage-sum')).toContainText(`已记录阶段合计 ${recordedSum} ms`);
    await expect(page.getByText('意图解析')).toHaveCount(0);

    await page.getByTestId('qa-stage-details').locator('summary').click();
    await expect(page.getByTestId('qa-stage-details')).toContainText('exact_recall');
    await expect(page.getByTestId('qa-stage-details')).toContainText('fact_validate');

    await openDrawerById(page, summary.request_ids.replayed);
    const replayAttempt = page.locator('[data-attempt="2"]');
    await expect(replayAttempt).toHaveAttribute('data-replayed', 'true');
    await expect(replayAttempt).toContainText('重放');
    await expect(page.getByTestId('qa-stage-replay')).toBeVisible();
    await expect(page.locator('[data-attempt="1"] [data-stage]')).toHaveCount(5);

    await openDrawerById(page, summary.request_ids.service_error);
    await expect(page.locator('[data-stage]')).toHaveCount(summary.detail.service_error.stages.length);
    await expect(page.locator('[data-stage="model_answer"]')).toContainText(summary.detail.service_error.error_code);
    await expect(page.getByText('答案校验')).toHaveCount(0);
    const stageValues = page.locator('.qa-stage-value');
    const values = await stageValues.allInnerTexts();
    expect(values.some((value) => value.trim() === '0 ms')).toBe(false);
  });

  test('Q7 Trace 关闭态：业务可读、阶段区显示已关闭', async ({ page }) => {
    const closed = summary.trace_closed_base;
    await loginAt(page, closed);
    await page.goto(`${closed}/operations/requests?window=7d&request_id=${summary.request_ids.answer_multi}`);
    await expect(page.getByTestId('qa-drawer')).toBeVisible();
    expect(new URL(page.url()).port).toBe('5302');

    await expect(page.getByTestId('qa-question')).toContainText('A 套餐');
    await expect(page.getByTestId('qa-result-badge')).toHaveText('已回答');
    await expect(page.locator(`[data-citation="${summary.detail.answer_multi.citation.document_id}"]`)).toContainText(
      '当前有效',
    );
    await expect(page.getByTestId('qa-trace-state')).toContainText('Trace 已关闭');
    await expect(page.getByTestId('qa-stages')).toHaveCount(0);
  });

  test('Q8 固定评测页签：批次、holdout 扣留、无发起入口、刷新保留', async ({ page }) => {
    await loginAt(page);
    await openRecords(page, 'window=7d');
    await page.getByTestId('qa-tab-eval').click();
    await expect(page).toHaveURL(/tab=eval/);
    await expect(page.getByTestId('qa-eval-table')).toBeVisible();

    const rows = page.locator('[data-run-id]');
    await expect(rows).toHaveCount(summary.eval.run_ids.length);
    for (const runId of summary.eval.run_ids) {
      const run = summary.eval.runs[runId];
      const row = page.locator(`[data-run-id="${runId}"]`);
      await expect(row).toContainText(runId);
      await expect(row.getByTestId('qa-eval-case-count')).toHaveText(String(run.case_count));
      await expect(row.getByTestId('qa-eval-status')).toHaveText(run.expected_status);
      if (run.details_withheld) {
        await expect(row).toContainText('holdout 明细已扣留');
      }
    }
    await expect(page.getByText('开始评测')).toHaveCount(0);
    await expect(page.getByText('重试评测')).toHaveCount(0);
    await expect(page.getByText('报告下载')).toHaveCount(0);

    await page.reload();
    await expect(page).toHaveURL(/tab=eval/);
    await expect(page.getByTestId('qa-eval-table')).toBeVisible();

    await page.locator('[data-view-run="qa-eval-b0-01"]').click();
    await expect(page.getByTestId('qa-eval-drawer')).toBeVisible();
    await expect(page.getByTestId('qa-eval-drawer')).toContainText('local');
    await expect(page.getByTestId('qa-eval-drawer')).toContainText('citation_hit');
    await expect(page.getByTestId('qa-eval-drawer')).toContainText('0.86');
    await expect(page.getByTestId('qa-eval-drawer')).toContainText('pass');
    await page.getByTestId('qa-eval-drawer-close').click();
    await expect(page.getByTestId('qa-eval-drawer')).toHaveCount(0);

    await page.locator('[data-view-run="qa-eval-holdout-01"]').click();
    await expect(page.getByTestId('qa-eval-drawer-withheld')).toContainText('仅聚合可见');
    await expect(page.getByTestId('qa-eval-drawer')).not.toContainText('leak-into-ui');
    await page.keyboard.press('Escape');

    await page.getByTestId('qa-tab-records').click();
    await expect(page).not.toHaveURL(/tab=eval/);
    await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();
  });

  test('Q9 权限闸门、详情 403、空态与失败重试', async ({ page }) => {
    await loginEmployee(page);
    await page.goto('/operations/requests?window=7d');
    await expect(page.getByText('知识运营仅限管理员')).toBeVisible();

    const detailResponse = await page.request.get(
      `/api/v1/operations/requests/${summary.request_ids.answer_multi}`,
    );
    expect(detailResponse.status()).toBe(403);

    await page.context().clearCookies();
    await page.goto('/login');
    await expect(page.getByRole('heading', { name: '登录', exact: true })).toBeVisible();
    await page.getByLabel('账号').fill(summary.accounts.admin.username);
    await page.getByLabel('密码').fill(summary.accounts.admin.password);
    await page.getByRole('button', { name: '登录', exact: true }).click();
    await expect(page).toHaveURL(/\/chat$/);

    await page.goto(
      `/operations/requests?window=custom&since=${summary.dates.empty_since}&until=${summary.dates.empty_until}`,
    );
    await expect(page.getByTestId('qa-empty')).toBeVisible();
    await expect(page.getByTestId('ops-placeholder-total')).toHaveText('0');

    const listPattern = /\/api\/v1\/operations\/requests\?/;
    await page.route(listPattern, (route) =>
      route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'boom' }) }),
    );
    await page.goto('/operations/requests?window=7d');
    await expect(page.getByTestId('qa-error')).toBeVisible();
    await expect(page.getByTestId('qa-retry')).toBeVisible();

    await page.unroute(listPattern);
    await page.getByTestId('qa-retry').click();
    await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();
    await expect(page.getByTestId('ops-placeholder-total')).toHaveText(String(summary.totals.week7d));
  });

  test('Q10 移动端 390px：筛选、打开与关闭抽屉', async ({ page }, testInfo) => {
    test.skip(testInfo.project.name !== 'mobile', 'Q10 只校验 390px 移动断点');
    await loginAt(page);
    await page.goto('/operations/requests?window=7d&kind=conflict');
    await expect(page.getByTestId('qa-filter-bar')).toBeVisible();
    await expect(page.getByTestId('ops-placeholder-total')).toHaveText(String(summary.totals.conflict_week));

    await page.getByTestId('qa-row').first().click();
    await expect(page.getByTestId('qa-drawer')).toBeVisible();
    const box = await page.getByTestId('qa-drawer').boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeLessThanOrEqual(390 + 0.5); // deviceScaleFactor=2 下会有亚像素误差

    await page.getByTestId('qa-drawer-close').click();
    await expect(page.getByTestId('qa-drawer')).toHaveCount(0);
    await expect(page.getByTestId('qa-filter-bar')).toBeVisible();
  });
});
