import fs from 'node:fs';
import path from 'node:path';
import { test, expect, type Page } from '@playwright/test';
import { D3_ROOT, EMPLOYEE, LABEL } from './support/acceptance';

/**
 * T09-D3 可选任务：Firefox / WebKit 本机内核最小冒烟（非真机）。
 *
 * 每条内核：未登录登录页 → 员工登录 → 单轮问答 Q03「城东店的展架在哪里？」
 * （断言 A区2号货架底层）→ 打开来源抽屉（断言「来源详情」+「物品位置表」/工作表 物品位置）→ 截图。
 *
 * 证据路径（不写正式 28 项证据目录）：
 * - 截图：D3/screenshots/<D3_LABEL>/xbrowser-<engine>/<name>.png
 * - 汇总：D3/actual/<D3_LABEL>/xbrowser-<engine>-smoke.json
 */

function engineOf(projectName: string): string {
  const engine = projectName.split('-')[0];
  return engine || projectName;
}

async function snap(page: Page, engine: string, name: string): Promise<string> {
  const target = path.join(D3_ROOT, 'screenshots', LABEL, `xbrowser-${engine}`, `${name}.png`);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  await page.screenshot({ path: target, animations: 'disabled' });
  return target;
}

test('本机内核冒烟：登录 → Q03 问答 → 来源抽屉', async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  const engine = engineOf(testInfo.project.name);
  const screenshots: string[] = [];

  await page.goto('/login');
  await expect(page.getByRole('heading', { name: '登录', exact: true })).toBeVisible({ timeout: 30_000 });
  screenshots.push(await snap(page, engine, '01-login'));

  await page.getByLabel('账号').fill(EMPLOYEE.username);
  await page.getByLabel('密码').fill(EMPLOYEE.password);
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await expect(page).toHaveURL(/\/chat$/, { timeout: 30_000 });
  await expect(page.getByRole('heading', { name: '有什么需要查询的？' })).toBeVisible();
  screenshots.push(await snap(page, engine, '02-chat-welcome'));

  const question = '城东店的展架在哪里？';
  await page.getByLabel('输入你的问题').fill(question);
  await page.getByRole('button', { name: '发送', exact: true }).click();
  const answer = page.locator('.message-assistant').last();
  await expect(answer).toContainText('A区2号货架底层', { timeout: 60_000 });
  await expect(answer.getByText('基于已发布资料')).toBeVisible();
  await expect(answer.getByText('来源与依据')).toBeVisible();
  screenshots.push(await snap(page, engine, '03-answer'));

  await answer.getByRole('button', { name: '查看依据' }).first().click();
  const drawer = page.getByRole('dialog', { name: '来源详情' });
  await expect(drawer.getByRole('heading', { name: '来源详情' })).toBeVisible();
  await expect(drawer).toContainText('物品位置表');
  await expect(drawer).toContainText('工作表 物品位置');
  screenshots.push(await snap(page, engine, '04-source-drawer'));

  const answerText = await answer.innerText();
  const drawerText = await drawer.innerText();
  const summary = {
    label: LABEL,
    kind: 'optional-xbrowser-smoke',
    note: '本机内核冒烟，非真机',
    engine,
    project: testInfo.project.name,
    browser_name: testInfo.project.use.browserName,
    user_agent: await page.evaluate(() => navigator.userAgent),
    viewport: page.viewportSize(),
    question,
    expected_answer: 'A区2号货架底层',
    answer_text: answerText.slice(0, 800),
    drawer_text: drawerText.slice(0, 800),
    assertions: {
      answer_has_expected_value: answerText.includes('A区2号货架底层'),
      drawer_has_title: drawerText.includes('来源详情'),
      drawer_has_document_name: drawerText.includes('物品位置表'),
      drawer_has_sheet_locator: drawerText.includes('工作表 物品位置'),
    },
    screenshots,
  };
  const summaryPath = path.join(D3_ROOT, 'actual', LABEL, `xbrowser-${engine}-smoke.json`);
  fs.mkdirSync(path.dirname(summaryPath), { recursive: true });
  fs.writeFileSync(summaryPath, `${JSON.stringify(summary, null, 2)}\n`, 'utf8');

  await drawer.getByRole('button', { name: '关闭来源详情' }).click();
  await expect(drawer).toHaveCount(0);
});
