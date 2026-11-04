import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from '@playwright/test';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(HERE, '..');
const R1A_ROOT = path.join(PROJECT_ROOT, 'docs', 'evidence', 'T08', 'R1A');
const PYTHON = path.join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe');
const DATA_DIR = path.join(R1A_ROOT, 'tmp', 'browser', '.e2e-data');
const BACKEND = process.env.R1A_BACKEND_ORIGIN || 'http://127.0.0.1:8098';
const BASE = process.env.R1A_BASE_URL || 'http://127.0.0.1:5198';

export default defineConfig({
  testDir: path.join(HERE, 'e2e-r1a'),
  testMatch: /07-.*\.spec\.ts/,
  globalSetup: path.join(HERE, 'e2e-r1a', 'setup.ts'),
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 120_000,
  expect: { timeout: 10_000 },
  reporter: [
    ['list'],
    ['html', { outputFolder: path.join(R1A_ROOT, 'playwright-report'), open: 'never' }],
  ],
  outputDir: path.join(R1A_ROOT, 'test-results'),
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
      name: 'r1a-functional',
      testMatch: /07-.*\.spec\.ts/,
      use: { browserName: 'chromium', viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 },
    },
  ],
  webServer: [
    {
      command: `"${PYTHON}" -B "${path.join(HERE, 'e2e-r1a', 'support', 'stub_server.py')}" --port 8098 --data-dir "${DATA_DIR}"`,
      url: `${BACKEND}/api/v1/healthz`,
      cwd: HERE,
      reuseExistingServer: false,
      timeout: 120_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      command: 'npm.cmd run dev -- --port 5198',
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
