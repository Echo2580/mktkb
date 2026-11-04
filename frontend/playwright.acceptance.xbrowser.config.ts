import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from '@playwright/test';

/**
 * T09-D3 可选任务：Firefox / WebKit 本机内核冒烟配置。
 *
 * - 只跑 `xbrowser-*.spec.ts`，与正式 28 项（`acceptance-*.spec.ts`）完全隔离；
 * - 服务器仍由运行器/人工在独立端口窗口启动，本配置**不配置 webServer**；
 * - 结果不写入正式轮证据目录：截图在 `screenshots/<D3_LABEL>/xbrowser-<engine>/`，
 *   JSON 报告缺省 `actual/playwright-xbrowser-<D3_LABEL>.json`；
 * - 本机内核冒烟，非真机。
 */
const HERE = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(HERE, '..');
const D3_ROOT = process.env.D3_EVIDENCE_ROOT
  ? path.resolve(process.env.D3_EVIDENCE_ROOT)
  : path.join(PROJECT_ROOT, 'docs', 'evidence', 'T09', 'D3');
const LABEL = process.env.D3_LABEL || 'unlabeled';
const PW_TMP = path.join(D3_ROOT, 'tmp', `pw-xbrowser-${LABEL}`);

export default defineConfig({
  testDir: path.join(HERE, 'e2e'),
  testMatch: /xbrowser-.*\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 120_000,
  expect: { timeout: 10_000 },
  outputDir: process.env.D3_PW_OUTPUT || path.join(PW_TMP, 'results'),
  reporter: [
    ['list'],
    [
      'json',
      {
        outputFile: process.env.D3_PW_JSON || path.join(D3_ROOT, 'actual', `playwright-xbrowser-${LABEL}.json`),
      },
    ],
  ],
  use: {
    baseURL: process.env.D3_BASE_URL || 'http://127.0.0.1:5199',
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    actionTimeout: 10_000,
    navigationTimeout: 20_000,
  },
  projects: [
    {
      name: 'firefox-1440x900',
      use: { browserName: 'firefox', viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 },
    },
    {
      name: 'webkit-1440x900',
      use: { browserName: 'webkit', viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 },
    },
  ],
});
