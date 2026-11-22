import { chromium } from '@playwright/test';
import path from 'node:path';

const OUT = path.resolve(
  '..',
  'docs',
  'reports',
  'OBS-EVAL',
  'P3',
  'T303-evidence',
  'rework',
  'screenshots',
);
const BASE = 'http://127.0.0.1:5299';

const browser = await chromium.launch();
for (const view of [
  { name: 'desktop', viewport: { width: 1440, height: 1400 }, deviceScaleFactor: 1 },
  { name: 'mobile', viewport: { width: 390, height: 2300 }, deviceScaleFactor: 2 },
]) {
  const context = await browser.newContext({
    baseURL: BASE,
    viewport: view.viewport,
    deviceScaleFactor: view.deviceScaleFactor,
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
  });
  const page = await context.newPage();
  await page.goto('/login');
  await page.getByLabel('账号').fill('admin');
  await page.getByLabel('密码').fill('AdminPass-1');
  await page.getByRole('button', { name: '登录', exact: true }).click();
  await page.waitForURL(/\/chat$/);
  await page.goto('/operations?window=7d');
  await page.getByTestId('ops-ready').waitFor();
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(OUT, `overview-${view.name}.png`), fullPage: true });
  await context.close();
}
await browser.close();
console.log('captured');

