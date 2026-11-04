import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from '@playwright/test';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(HERE, '..');
const PYTHON = path.join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe');
const DATA_DIR = path.join(HERE, '.e2e-data');
const BACKEND = process.env.T08_BACKEND_ORIGIN || 'http://127.0.0.1:8077';
const BASE = process.env.T08_BASE_URL || 'http://127.0.0.1:5173';

export default defineConfig({
  testDir: path.join(HERE, 'e2e'),
  globalSetup: path.join(HERE, 'e2e', 'global.setup.ts'),
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 90_000,
  expect: { timeout: 10_000 },
  reporter: [
    ['list'],
    ['html', { outputFolder: path.join(HERE, 'playwright-report'), open: 'never' }],
  ],
  outputDir: path.join(HERE, 'test-results'),
  use: {
    baseURL: BASE,
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    actionTimeout: 10_000,
    navigationTimeout: 20_000,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    {
      name: 'functional',
      testMatch: /0[1-4]-.*\.spec\.ts/,
      use: { browserName: 'chromium', viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 },
    },
    {
      name: 'responsive-390',
      testMatch: /05-responsive\.spec\.ts/,
      use: {
        browserName: 'chromium',
        viewport: { width: 390, height: 844 },
        deviceScaleFactor: 1,
        isMobile: true,
        hasTouch: true,
      },
    },
    {
      name: 'responsive-375',
      testMatch: /05-responsive\.spec\.ts/,
      use: {
        browserName: 'chromium',
        viewport: { width: 375, height: 844 },
        deviceScaleFactor: 1,
        isMobile: true,
        hasTouch: true,
      },
    },
    {
      name: 'layout-1440x900',
      testMatch: /06-layout\.spec\.ts/,
      use: { browserName: 'chromium', viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 },
    },
    {
      name: 'layout-1366',
      testMatch: /06-layout\.spec\.ts/,
      use: { browserName: 'chromium', viewport: { width: 1366, height: 768 }, deviceScaleFactor: 1 },
    },
    {
      name: 'layout-1440x720',
      testMatch: /06-layout\.spec\.ts/,
      use: { browserName: 'chromium', viewport: { width: 1440, height: 720 }, deviceScaleFactor: 1 },
    },
  ],
  webServer: [
    {
      command: `"${PYTHON}" -B "${path.join(HERE, 'e2e', 'support', 'stub_server.py')}" --port 8077 --data-dir "${DATA_DIR}"`,
      url: `${BACKEND}/api/v1/healthz`,
      cwd: HERE,
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      command: 'npm.cmd run dev',
      url: BASE,
      cwd: HERE,
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: 'pipe',
      stderr: 'pipe',
      env: { T08_BACKEND_ORIGIN: BACKEND },
    },
  ],
});
