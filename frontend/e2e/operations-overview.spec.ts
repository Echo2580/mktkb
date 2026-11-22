import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { expect, test, type Page } from '@playwright/test';

/**
 * T303 运营总览 Playwright 用例 P1-P11。
 * 数据来自隔离目录的受控种子（operations-seed.py）；不发问答 POST，不调真实模型。
 */

interface Metrics {
  completed: number;
  not_found: number;
  conflict: number;
  review: number;
  interrupted: number;
  active_documents: number;
  pending: number;
  trend_days: number;
  distribution: Record<string, number>;
  trend: Array<{ date: string; completed: number; citations: number }>;
}

interface Summary {
  dates: { today: string; yesterday: string; ten_days_ago: string; empty_since: string; empty_until: string };
  accounts: { admin: { username: string; password: string }; employee: { username: string; password: string } };
  metrics: { week7d: Metrics; today: Metrics; month30d: Metrics; yesterday: Metrics; empty: Metrics };
  requests: { week: number; today: number; yesterday: number; conflict_week: number };
  documents: {
    review_total: number;
    failed_total: number;
    failed_document_id: string;
    failed_version_id: string;
    failed_state: string;
    review_document_id: string;
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
  'T303-evidence',
  'isolated-var',
  'seed-summary.json',
);

const summary: Summary = JSON.parse(fs.readFileSync(SUMMARY_PATH, 'utf8'));

async function login(page: Page, role: 'admin' | 'employee'): Promise<void> {
  const account = summary.accounts[role];
  await page.goto('/login');
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

function query(url: string): URLSearchParams {
  return new URL(url).searchParams;
}

async function expectCard(page: Page, testId: string, value: number): Promise<void> {
  await expect(page.getByTestId(testId)).toHaveText(String(value));
}

async function waitOverview(page: Page, params: Record<string, string>): Promise<void> {
  const response = await page.waitForResponse((candidate) => {
    if (!candidate.url().includes('/api/v1/operations/overview')) return false;
    if (candidate.request().method() !== 'GET') return false;
    const search = query(candidate.url());
    return Object.entries(params).every(([key, value]) => search.get(key) === value);
  });
  expect(response.status()).toBe(200);
  await expect(page.getByTestId('ops-ready')).toBeVisible();
}

test.describe('T303 运营总览', () => {
  test('P1 admin 登录后从侧栏进入总览，卡片/两图/待处理与种子一致', async ({ page }, testInfo) => {
    await login(page, 'admin');
    const nav = page.getByRole('navigation', { name: '主要导航' });
    if (testInfo.project.name === 'mobile') {
      await page.getByRole('button', { name: '打开菜单' }).click();
      await expect(nav.getByRole('link', { name: '知识运营' })).toBeVisible();
      await nav.getByRole('link', { name: '知识运营' }).click();
    } else {
      await expect(nav.getByRole('link', { name: '知识运营' })).toBeVisible();
      await nav.getByRole('link', { name: '知识运营' }).click();
    }
    await expect(page).toHaveURL(/\/operations$/);
    await expect(page.getByTestId('ops-ready')).toBeVisible();
    await expect(page.locator('.topbar-title')).toHaveText('知识运营');

    const week = summary.metrics.week7d;
    await expectCard(page, 'ops-metric-completed', week.completed);
    await expectCard(page, 'ops-metric-not_found', week.not_found);
    await expectCard(page, 'ops-metric-conflict', week.conflict);
    await expectCard(page, 'ops-metric-review_required_versions', week.review);
    await expectCard(page, 'ops-metric-interrupted', week.interrupted);
    await expectCard(page, 'ops-metric-active_documents', week.active_documents);

    await expect(page.getByTestId('ops-metric-review-card')).toContainText('当前');
    await expect(page.getByTestId('ops-chart-trend').locator('canvas')).toHaveCount(1);
    await expect(page.getByTestId('ops-chart-distribution').locator('canvas')).toHaveCount(1);
    await expect(page.locator('[data-pending-request]')).toHaveCount(week.pending - 1);
    await expect(page.locator('[data-pending-import]')).toHaveCount(1);
    await expect(page.getByTestId('ops-trace')).toContainText('Trace 已关闭');
  });

  test('P2 employee 无入口、直达被门禁，接口直调 403', async ({ page }) => {
    await login(page, 'employee');
    const nav = page.getByRole('navigation', { name: '主要导航' });
    if (page.viewportSize()!.width < 600) {
      await page.getByRole('button', { name: '打开菜单' }).click();
    }
    await expect(nav.getByRole('link', { name: '知识运营' })).toHaveCount(0);

    const operationCalls: string[] = [];
    page.on('request', (request) => {
      if (request.url().includes('/api/v1/operations/')) operationCalls.push(request.url());
    });
    await page.goto('/operations');
    await expect(page.getByText('知识运营仅限管理员')).toBeVisible();
    await expect(page.getByTestId('ops-ready')).toHaveCount(0);
    expect(operationCalls).toHaveLength(0);

    const direct = await page.request.get('/api/v1/operations/overview?window=7d');
    expect(direct.status()).toBe(403);
    const payload = await direct.json();
    expect(payload.error.code).toBe('ROLE_REQUIRED');
  });

  test('P3 日期切换 today/7d/30d/自定义，趋势与分布同步更新且请求参数一致', async ({ page }) => {
    await openOverview(page);
    const week = summary.metrics.week7d;
    const today = summary.metrics.today;
    const month = summary.metrics.month30d;
    const yesterday = summary.metrics.yesterday;

    const seen: string[] = [];
    page.on('request', (request) => {
      if (request.url().includes('/api/v1/operations/overview')) seen.push(request.url());
    });

    const before = seen.length;
    const todayWait = waitOverview(page, { window: 'today' });
    await page.locator('[data-window-option="today"]').click();
    await todayWait;
    await expectCard(page, 'ops-metric-completed', today.completed);
    await expect(page.locator('[data-kind="answer"]')).toContainText(`· ${today.distribution.answer}`);
    await expect(page.getByTestId('ops-trend-empty')).toHaveCount(0);
    await expect(page.locator('[data-trend-date]')).toHaveCount(today.trend_days);
    expect(seen.length).toBe(before + 1);
    const todayUrl = new URL(seen[seen.length - 1]);
    expect(todayUrl.searchParams.get('window')).toBe('today');
    expect(todayUrl.searchParams.get('since')).toBeNull();
    expect(todayUrl.searchParams.get('kind')).toBeNull();

    const before30 = seen.length;
    const monthWait = waitOverview(page, { window: '30d' });
    await page.locator('[data-window-option="30d"]').click();
    await monthWait;
    await expectCard(page, 'ops-metric-completed', month.completed);
    await expect(page.locator('[data-kind="answer"]')).toContainText(`· ${month.distribution.answer}`);
    expect(seen.length).toBe(before30 + 1);
    expect(query(seen[seen.length - 1]).get('window')).toBe('30d');

    const before7 = seen.length;
    const weekWait = waitOverview(page, { window: '7d' });
    await page.locator('[data-window-option="7d"]').click();
    await weekWait;
    await expectCard(page, 'ops-metric-completed', week.completed);
    await expect(page.locator('[data-kind="answer"]')).toContainText(`· ${week.distribution.answer}`);
    expect(seen.length).toBe(before7 + 1);
    expect(query(seen[seen.length - 1]).get('window')).toBe('7d');

    await page.locator('[data-window-option="custom"]').click();
    await expect(page).toHaveURL(/window=custom/);
    const dateInputs = page.locator('input[type="date"]');
    await dateInputs.nth(0).fill(summary.dates.yesterday);
    await dateInputs.nth(1).fill(summary.dates.yesterday);
    const customWait = waitOverview(page, { since: summary.dates.yesterday, until: summary.dates.yesterday });
    await page.getByRole('button', { name: '应用', exact: true }).click();
    await customWait;
    await expectCard(page, 'ops-metric-completed', yesterday.completed);
    await expect(page.locator('[data-kind="answer"]')).toContainText(`· ${yesterday.distribution.answer}`);
    const customUrl = new URL(page.url());
    expect(customUrl.searchParams.get('since')).toBe(summary.dates.yesterday);
    expect(customUrl.searchParams.get('until')).toBe(summary.dates.yesterday);
  });

  test('P4 点击趋势某天 → 该日窗口，占位页总数 == 总览该日完成量', async ({ page }) => {
    await openOverview(page);
    const chart = page.getByTestId('ops-chart-trend');
    const box = await chart.boundingBox();
    expect(box).not.toBeNull();
    const points = summary.metrics.week7d.trend;
    const last = points[points.length - 1];
    const x = 48 + (box!.width - 72) * 0.75;
    await chart.click({ position: { x, y: box!.height * 0.5 } });

    await expect(page).toHaveURL(/\/operations\/requests/);
    const search = new URL(page.url()).searchParams;
    expect(search.get('since')).toBe(last.date);
    expect(search.get('until')).toBe(last.date);
    expect(search.get('window')).toBe('custom');
    await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();
    await expect(page.getByTestId('ops-placeholder-total')).toHaveText(String(summary.requests.today));
    expect(summary.requests.today).toBe(summary.metrics.today.completed);
  });

  test('P5 只用 Tab/Enter 完成日期下钻与类别下钻，结果与鼠标一致', async ({ page }) => {
    await openOverview(page);

    let dateFound = false;
    for (let i = 0; i < 140; i += 1) {
      await page.keyboard.press('Tab');
      const attribute = await page.evaluate(() => document.activeElement?.getAttribute('data-trend-date'));
      if (attribute) {
        dateFound = true;
        break;
      }
    }
    expect(dateFound).toBe(true);
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/\/operations\/requests/);
    const daySearch = new URL(page.url()).searchParams;
    const clickedDate = daySearch.get('since');
    expect(clickedDate).toBeTruthy();
    expect(daySearch.get('until')).toBe(clickedDate);
    await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();
    const dayTotal = Number(await page.getByTestId('ops-placeholder-total').innerText());

    await page.goBack();
    await expect(page.getByTestId('ops-ready')).toBeVisible();

    let kindFound = false;
    for (let i = 0; i < 140; i += 1) {
      await page.keyboard.press('Tab');
      const attribute = await page.evaluate(() => document.activeElement?.getAttribute('data-kind'));
      if (attribute === 'conflict') {
        kindFound = true;
        break;
      }
    }
    expect(kindFound).toBe(true);
    await page.keyboard.press('Enter');
    await expect(page).toHaveURL(/\/operations\/requests/);
    expect(new URL(page.url()).searchParams.get('kind')).toBe('conflict');
    await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();
    const kindTotal = Number(await page.getByTestId('ops-placeholder-total').innerText());

    expect(dayTotal).toBeGreaterThan(0);
    expect(kindTotal).toBe(summary.requests.conflict_week);
  });

  test('P6 点击分布 conflict → URL 带 kind 与当前窗口，占位页总数 == conflict 计数', async ({ page }) => {
    await openOverview(page);
    await page.locator('.ops-keyboard-list [data-kind="conflict"]').click();
    await expect(page).toHaveURL(/\/operations\/requests/);
    const search = new URL(page.url()).searchParams;
    expect(search.get('kind')).toBe('conflict');
    expect(search.get('window')).toBe('7d');
    await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();
    await expect(page.getByTestId('ops-placeholder-total')).toHaveText(String(summary.requests.conflict_week));
    expect(summary.requests.conflict_week).toBe(summary.metrics.week7d.conflict);
    await expect(page.getByTestId('ops-placeholder-kind')).toContainText('conflict');
  });

  test('P7 点击待处理导入失败项 → documents 占位页带 document_id/state，总数一致', async ({ page }) => {
    await openOverview(page);
    await page.locator('[data-pending-import]').first().click();
    await expect(page).toHaveURL(/\/operations\/documents/);
    const search = new URL(page.url()).searchParams;
    expect(search.get('document_id')).toBe(summary.documents.failed_document_id);
    expect(search.get('state')).toBe(summary.documents.failed_state);
    await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();
    await expect(page.getByTestId('ops-placeholder-total')).toHaveText(String(summary.documents.failed_total));
    await expect(page.getByTestId('ops-placeholder-document')).toHaveText(summary.documents.failed_document_id);
    await expect(page.getByTestId('ops-placeholder-state')).toContainText(summary.documents.failed_state);
  });

  test('P8 刷新与浏览器返回保留筛选', async ({ page }) => {
    await openOverview(page);
    await page.locator('[data-window-option="30d"]').click();
    await expectCard(page, 'ops-metric-completed', summary.metrics.month30d.completed);
    expect(query(page.url()).get('window')).toBe('30d');

    await page.locator('.ops-keyboard-list [data-kind="conflict"]').click();
    await expect(page).toHaveURL(/\/operations\/requests/);
    expect(query(page.url()).get('window')).toBe('30d');

    await page.goBack();
    await expect(page).toHaveURL(/\/operations/);
    await expect(page.getByTestId('ops-ready')).toBeVisible();
    expect(query(page.url()).get('window')).toBe('30d');
    await expectCard(page, 'ops-metric-completed', summary.metrics.month30d.completed);

    await page.reload();
    await expect(page.getByTestId('ops-ready')).toBeVisible();
    expect(query(page.url()).get('window')).toBe('30d');
    await expectCard(page, 'ops-metric-completed', summary.metrics.month30d.completed);
    await expect(page.locator('[data-window-option="30d"]')).toHaveAttribute('aria-pressed', 'true');
  });

  test('P9 空窗口：计 0、图表与列表空态、无假百分比', async ({ page }) => {
    await openOverview(page);
    await page.locator('[data-window-option="custom"]').click();
    const dateInputs = page.locator('input[type="date"]');
    await dateInputs.nth(0).fill(summary.dates.empty_since);
    await dateInputs.nth(1).fill(summary.dates.empty_until);
    const emptyWait = waitOverview(page, {
      since: summary.dates.empty_since,
      until: summary.dates.empty_until,
    });
    await page.getByRole('button', { name: '应用', exact: true }).click();
    await emptyWait;

    await expectCard(page, 'ops-metric-completed', 0);
    await expectCard(page, 'ops-metric-not_found', 0);
    await expectCard(page, 'ops-metric-conflict', 0);
    await expect(page.getByTestId('ops-trend-empty')).toBeVisible();
    await expect(page.getByTestId('ops-dist-empty')).toBeVisible();
    await expect(page.getByTestId('ops-chart-trend')).toHaveCount(0);
    await expect(page.getByTestId('ops-chart-distribution')).toHaveCount(0);
    // T302 的 pending 导入项是库存口径、不随窗口回溯；空窗口下仍可能列出失败导入。
    await expect(page.locator('[data-pending-request]')).toHaveCount(0);
    const emptyPending = summary.metrics.empty.pending;
    await expect(page.locator('[data-pending-import]')).toHaveCount(emptyPending);
    if (emptyPending === 0) await expect(page.getByTestId('ops-pending-empty')).toBeVisible();
    const text = await page.locator('.page').innerText();
    expect(text).not.toContain('NaN');
    expect(text).not.toMatch(/\d+(\.\d+)?%/);
  });

  test('P10 移动端 390 完成日期切换与一次下钻', async ({ page }, testInfo) => {
    expect(page.viewportSize()).toEqual(
      testInfo.project.name === 'mobile' ? { width: 390, height: 844 } : { width: 1440, height: 900 },
    );
    await openOverview(page);
    await page.locator('[data-window-option="today"]').click();
    await expectCard(page, 'ops-metric-completed', summary.metrics.today.completed);
    expect(query(page.url()).get('window')).toBe('today');

    await page.locator('.ops-keyboard-list [data-kind="conflict"]').click();
    await expect(page).toHaveURL(/\/operations\/requests/);
    expect(query(page.url()).get('kind')).toBe('conflict');
    await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();
    await expect(page.getByTestId('ops-placeholder-total')).toHaveText(String(summary.metrics.today.conflict));
  });

  test('P11 运营接口 500/断网显示错误，恢复后重试成功', async ({ page }) => {
    await login(page, 'admin');
    await page.route('**/api/v1/operations/overview*', (route) =>
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: { code: 'INTERNAL_ERROR', message: '受控故障', retryable: true } }),
      }),
    );
    await page.goto('/operations');
    await expect(page.getByTestId('ops-error')).toBeVisible();
    await expect(page.getByTestId('ops-retry')).toBeVisible();
    await expect(page.getByTestId('ops-ready')).toHaveCount(0);

    await page.unroute('**/api/v1/operations/overview*');
    await page.getByTestId('ops-retry').click();
    await expect(page.getByTestId('ops-ready')).toBeVisible();
    await expectCard(page, 'ops-metric-completed', summary.metrics.week7d.completed);
  });

  test('P12 三页签均在位、可切换且高亮正确，往返不丢筛选', async ({ page }) => {
    await openOverview(page);
    const tabs = page.getByRole('navigation', { name: '运营工作台页面' });
    await expect(tabs.getByRole('link')).toHaveCount(3);
    await expect(tabs.getByRole('link', { name: '运营总览' })).toHaveAttribute('aria-current', 'page');
    await expect(page.getByText('只读工作台', { exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: /前往资料管理/ })).toBeVisible();

    await page.locator('[data-window-option="30d"]').click();
    await expectCard(page, 'ops-metric-completed', summary.metrics.month30d.completed);
    expect(query(page.url()).get('window')).toBe('30d');

    await tabs.getByRole('link', { name: '问答诊断' }).click();
    await expect(page).toHaveURL(/\/operations\/requests\?/);
    expect(query(page.url()).get('window')).toBe('30d');
    await expect(tabs.getByRole('link', { name: '问答诊断' })).toHaveAttribute('aria-current', 'page');
    await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();

    await tabs.getByRole('link', { name: '知识资产' }).click();
    await expect(page).toHaveURL(/\/operations\/documents\?/);
    expect(query(page.url()).get('window')).toBe('30d');
    await expect(tabs.getByRole('link', { name: '知识资产' })).toHaveAttribute('aria-current', 'page');
    await expect(page.getByTestId('ops-placeholder-ready')).toBeVisible();

    await tabs.getByRole('link', { name: '运营总览' }).click();
    await expect(page).toHaveURL(/\/operations\?/);
    expect(query(page.url()).get('window')).toBe('30d');
    await expect(page.getByTestId('ops-ready')).toBeVisible();
    await expectCard(page, 'ops-metric-completed', summary.metrics.month30d.completed);
    await expect(tabs.getByRole('link', { name: '运营总览' })).toHaveAttribute('aria-current', 'page');
  });

  test('P13 未找到副注百分比与卡片数值一致，空窗口无样本；Trace 中文映射无英文回显', async ({ page }) => {
    await openOverview(page);
    const week = summary.metrics.week7d;
    const expectedShare = `占全部问答 ${((week.not_found / week.completed) * 100).toFixed(1)}%`;
    await expect(page.getByTestId('ops-metric-not_found')).toHaveText(String(week.not_found));
    await expect(page.getByTestId('ops-not-found-share')).toHaveText(expectedShare);
    await expect(page.getByTestId('ops-metric-conflict-card')).toContainText('需管理员核实');
    await expect(page.getByTestId('ops-metric-review-card')).toContainText('与日期筛选无关');

    const traceText = await page.getByTestId('ops-trace').innerText();
    expect(traceText).not.toMatch(/recorded|partial|disabled|unavailable|not_recorded/);
    expect(traceText).toMatch(/已记录|部分覆盖|Trace 已关闭|Trace 暂不可用|未记录|状态未知/);

    const overviewResponse = await page.request.get('/api/v1/operations/overview?window=30d');
    expect(overviewResponse.status()).toBe(200);
    const payload = await overviewResponse.json();
    payload.trace_coverage = { status: 'recorded', covered: 3, total: 7, note: null };
    await page.route('**/api/v1/operations/overview*', (route) => route.fulfill({ json: payload }));
    const recordedWait = page.waitForResponse((candidate) =>
      candidate.url().includes('/api/v1/operations/overview?window=30d'),
    );
    await page.goto('/operations?window=30d');
    await recordedWait;
    await expect(page.getByTestId('ops-trace')).toHaveText('已记录 · 3/7');
    await page.unroute('**/api/v1/operations/overview*');

    await page.locator('[data-window-option="custom"]').click();
    const dateInputs = page.locator('input[type="date"]');
    await dateInputs.nth(0).fill(summary.dates.empty_since);
    await dateInputs.nth(1).fill(summary.dates.empty_until);
    const emptyWait = waitOverview(page, {
      since: summary.dates.empty_since,
      until: summary.dates.empty_until,
    });
    await page.getByRole('button', { name: '应用', exact: true }).click();
    await emptyWait;
    await expect(page.getByTestId('ops-not-found-share')).toHaveText('无样本');
    await expect(page.locator('.page')).not.toContainText('NaN');
  });
});
