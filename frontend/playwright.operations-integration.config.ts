import path from 'node:path';
import { defineConfig } from '@playwright/test';
import { fileURLToPath } from 'node:url';

/**
 * T306 集成验收配置（I1-I8）。
 * - 双后端双前端：主栈 8291/5303，Trace 关闭栈 8293/5304（数据目录共用同一隔离库）；
 * - 数据只来自 T306-evidence/isolated-var（由 operations-integration-seed.py 生成）；
 * - desktop 1440×900 + mobile 390×844 两个 project；
 * - 自动启动/关闭：gracefulShutdown + ignore 输出，预览前端用 node 直启，避免 cmd 壳挂住；
 * - 轮次证据写到 T306-evidence/rounds/<UTC 时间戳>/，不覆盖既有证据。
 */

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(HERE, '..');
const EVIDENCE_ROOT = path.join(PROJECT_ROOT, 'docs', 'reports', 'OBS-EVAL', 'P3', 'T306-evidence');
const ISOLATED_DIR = path.join(EVIDENCE_ROOT, 'isolated-var');
const PYTHON = path.join(PROJECT_ROOT, '.venv', 'Scripts', 'python.exe');
const ROUND_DIR = path.join(EVIDENCE_ROOT, 'rounds', new Date().toISOString().replace(/[:.]/g, '-'));
const CSRF_SECRET = 'p3-e2e-csrf-secret-0123456789';

function backend(port: number, traceEnabled: boolean, frontendOrigin: string) {
  return {
    command: `"${PYTHON}" -B -m uvicorn mktkb.main:create_app --factory --host 127.0.0.1 --port ${port}`,
    cwd: path.join(PROJECT_ROOT, 'backend'),
    url: `http://127.0.0.1:${port}/api/v1/healthz`,
    timeout: 180_000,
    reuseExistingServer: false,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 1000 },
    stdout: 'ignore' as const,
    stderr: 'ignore' as const,
    env: {
      PYTHONPATH: path.join(PROJECT_ROOT, 'backend', 'src'),
      PYTHONDONTWRITEBYTECODE: '1',
      MKTKB_DATA_DIR: ISOLATED_DIR,
      MKTKB_DATABASE_URL: `sqlite:///${path.join(ISOLATED_DIR, 'mktkb.sqlite3')}`,
      MKTKB_ADMIN_PASSWORD: 'AdminPass-1',
      MKTKB_EMPLOYEE_PASSWORD: 'EmployeePass-1',
      MKTKB_CSRF_SECRET: CSRF_SECRET,
      MKTKB_TRUSTED_ORIGINS: JSON.stringify([frontendOrigin]),
      MKTKB_COOKIE_SECURE: '0',
      MKTKB_BCRYPT_ROUNDS: '4',
      MKTKB_TRACE_ENABLED: traceEnabled ? '1' : '0',
      MKTKB_RAG_QA_ENABLED: '0',
    },
  };
}

function preview(port: number, backendPort: number) {
  return {
    command: `node node_modules/vite/bin/vite.js preview --port ${port} --strictPort`,
    cwd: HERE,
    url: `http://127.0.0.1:${port}`,
    timeout: 120_000,
    reuseExistingServer: false,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 1000 },
    stdout: 'ignore' as const,
    stderr: 'ignore' as const,
    env: { T08_BACKEND_ORIGIN: `http://127.0.0.1:${backendPort}` },
  };
}

export default defineConfig({
  testDir: './e2e',
  testMatch: /operations-integration.*\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 120_000,
  expect: { timeout: 10_000 },
  outputDir: path.join(EVIDENCE_ROOT, 'playwright-results'),
  reporter: [
    ['list'],
    ['json', { outputFile: path.join(ROUND_DIR, 'playwright-integration.json') }],
    ['html', { outputFolder: path.join(ROUND_DIR, 'playwright-report'), open: 'never' }],
  ],
  use: {
    baseURL: 'http://127.0.0.1:5303',
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    colorScheme: 'light',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'desktop',
      use: {
        browserName: 'chromium',
        viewport: { width: 1440, height: 900 },
        deviceScaleFactor: 1,
        launchOptions: { args: ['--disable-gpu', '--disable-software-rasterizer', '--disable-dev-shm-usage'] },
      },
    },
    {
      name: 'mobile',
      use: {
        browserName: 'chromium',
        viewport: { width: 390, height: 844 },
        deviceScaleFactor: 2,
        launchOptions: { args: ['--disable-gpu', '--disable-software-rasterizer', '--disable-dev-shm-usage'] },
      },
    },
  ],
  webServer: [
    backend(8291, true, 'http://127.0.0.1:5303'),
    preview(5303, 8291),
    backend(8293, false, 'http://127.0.0.1:5304'),
    preview(5304, 8293),
  ],
});
