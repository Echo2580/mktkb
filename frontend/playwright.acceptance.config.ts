import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from '@playwright/test';

/**
 * T09-D3 B 层浏览器验收配置（契约 §3）。
 *
 * - 只跑 `acceptance-*.spec.ts`，带旧 e2e 01-06 responsive/layout 也不会被选中；
 * - 服务器（后端 8188 + Vite 5199）由 `run_browser_acceptance.py` 启动与停服，
 *   本配置**不配置 webServer**，所有日志/证据路径由运行器通过 D3_* env 传入；
 * - 串行执行（workers=1）、不重试、禁止 only，保证跨 spec 的状态累积顺序稳定。
 */
const HERE = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(HERE, '..');
const D3_ROOT = process.env.D3_EVIDENCE_ROOT
  ? path.resolve(process.env.D3_EVIDENCE_ROOT)
  : path.join(PROJECT_ROOT, 'docs', 'evidence', 'T09', 'D3');
const LABEL = process.env.D3_LABEL || 'unlabeled';
const PW_TMP = path.join(D3_ROOT, 'tmp', `pw-${LABEL}`);

export default defineConfig({
  testDir: path.join(HERE, 'e2e'),
  testMatch: /acceptance-.*\.spec\.ts/,
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
        outputFile: process.env.D3_PW_JSON || path.join(D3_ROOT, 'actual', `playwright-${LABEL}.json`),
      },
    ],
    [
      'html',
      {
        outputFolder: process.env.D3_PW_HTML || path.join(PW_TMP, 'report'),
        open: 'never',
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
      name: 'acceptance-chromium',
      use: {
        browserName: 'chromium',
        viewport: { width: 1440, height: 900 },
        deviceScaleFactor: 1,
      },
    },
  ],
});
