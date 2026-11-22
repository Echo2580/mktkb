import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from '@playwright/test';

/**
 * T303 运营页专用 Playwright 配置。
 * - 只选 operations-overview*.spec.ts（T306 收窄，避免串跑 qa/assets），不影响既有 acceptance/e2e 配置；
 * - webServer 使用隔离数据目录（MKTKB_DATA_DIR），绝不写 backend/var；
 * - 串行、不重试、禁止 only；桌面 + 移动两个 project。
 */
const HERE = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(HERE, '..');
const EVIDENCE_ROOT = path.join(PROJECT_ROOT, 'docs', 'reports', 'OBS-EVAL', 'P3', 'T303-evidence');
const ISOLATED_DIR = path.join(EVIDENCE_ROOT, 'isolated-var');
/** 每次执行生成独立轮次子目录（UTC 时间戳），只新增、不覆盖既有 json/html 证据。 */
const ROUND_DIR = path.join(EVIDENCE_ROOT, 'rounds', new Date().toISOString().replace(/[:.]/g, '-'));

const ADMIN_PASSWORD = 'AdminPass-1';
const EMPLOYEE_PASSWORD = 'EmployeePass-1';
const CSRF_SECRET = 'p3-e2e-csrf-secret-0123456789';

export default defineConfig({
  testDir: path.join(HERE, 'e2e'),
  testMatch: /operations-overview.*\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 120_000,
  expect: { timeout: 10_000 },
  outputDir: path.join(EVIDENCE_ROOT, 'playwright-results'),
  reporter: [
    ['list'],
    ['json', { outputFile: path.join(ROUND_DIR, 'playwright-operations.json') }],
    ['html', { outputFolder: path.join(ROUND_DIR, 'playwright-report'), open: 'never' }],
  ],
  use: {
    baseURL: 'http://127.0.0.1:5299',
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
      name: 'desktop',
      use: { browserName: 'chromium', viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 },
    },
    {
      name: 'mobile',
      use: { browserName: 'chromium', viewport: { width: 390, height: 844 }, deviceScaleFactor: 2 },
    },
  ],
  webServer: [
    {
      command:
        '..\\.venv\\Scripts\\python.exe -B -m uvicorn mktkb.main:create_app --factory --host 127.0.0.1 --port 8288',
      cwd: path.join(PROJECT_ROOT, 'backend'),
      url: 'http://127.0.0.1:8288/api/v1/healthz',
      timeout: 180_000,
      reuseExistingServer: false,
      gracefulShutdown: { signal: 'SIGTERM', timeout: 1000 },
      stdout: 'ignore',
      stderr: 'ignore',
      env: {
        PYTHONPATH: path.join(PROJECT_ROOT, 'backend', 'src'),
        MKTKB_DATA_DIR: ISOLATED_DIR,
        MKTKB_ADMIN_PASSWORD: ADMIN_PASSWORD,
        MKTKB_EMPLOYEE_PASSWORD: EMPLOYEE_PASSWORD,
        MKTKB_CSRF_SECRET: CSRF_SECRET,
        MKTKB_TRUSTED_ORIGINS: '["http://127.0.0.1:5299"]',
        MKTKB_TRACE_ENABLED: 'false',
        MKTKB_RAG_QA_ENABLED: 'false',
      },
    },
    {
      command: 'node node_modules/vite/bin/vite.js preview --port 5299 --strictPort',
      cwd: HERE,
      url: 'http://127.0.0.1:5299',
      timeout: 120_000,
      reuseExistingServer: false,
      gracefulShutdown: { signal: 'SIGTERM', timeout: 1000 },
      stdout: 'ignore',
      stderr: 'ignore',
      env: {
        T08_BACKEND_ORIGIN: 'http://127.0.0.1:8288',
      },
    },
  ],
});
