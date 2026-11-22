import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from '@playwright/test';

/**
 * T304 问答诊断专用 Playwright 配置。
 * - 只选 operations-qa*.spec.ts，不覆盖 T303 的 operations-*.spec.ts；
 * - webServer 使用隔离数据目录（MKTKB_DATA_DIR），绝不写 backend/var；
 * - 主栈：8289 + preview 5300（Trace 开启）；
 * - 关闭态栈：8292 + preview 5302（Trace 关闭，仅 Q7 使用），与 T305（8290/5301）错开；
 * - 串行、不重试、禁止 only；桌面 + 移动两个 project。
 */
const HERE = path.dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = path.resolve(HERE, '..');
const EVIDENCE_ROOT = path.join(PROJECT_ROOT, 'docs', 'reports', 'OBS-EVAL', 'P3', 'T304-evidence');
const ISOLATED_DIR = path.join(EVIDENCE_ROOT, 'isolated-var');
/** 每次执行生成独立轮次子目录（UTC 时间戳），只新增、不覆盖既有 json/html 证据。 */
const ROUND_DIR = path.join(EVIDENCE_ROOT, 'rounds', new Date().toISOString().replace(/[:.]/g, '-'));

const ADMIN_PASSWORD = 'AdminPass-1';
const EMPLOYEE_PASSWORD = 'EmployeePass-1';
const CSRF_SECRET = 'p3-e2e-csrf-secret-0123456789';

const BACKEND_ENV = {
  PYTHONPATH: path.join(PROJECT_ROOT, 'backend', 'src'),
  MKTKB_DATA_DIR: ISOLATED_DIR,
  MKTKB_ADMIN_PASSWORD: ADMIN_PASSWORD,
  MKTKB_EMPLOYEE_PASSWORD: EMPLOYEE_PASSWORD,
  MKTKB_CSRF_SECRET: CSRF_SECRET,
  MKTKB_RAG_QA_ENABLED: 'false',
  // 本机系统提交额度紧张时 OpenBLAS 按核数预分配会直接失败，这里限制数学库线程数
  OPENBLAS_NUM_THREADS: '1',
  OMP_NUM_THREADS: '1',
  MKL_NUM_THREADS: '1',
};

const MAIN_STACK = [
  {
    command:
      '..\\.venv\\Scripts\\python.exe -B -m uvicorn mktkb.main:create_app --factory --host 127.0.0.1 --port 8289',
    cwd: path.join(PROJECT_ROOT, 'backend'),
    url: 'http://127.0.0.1:8289/api/v1/healthz',
    timeout: 180_000,
    reuseExistingServer: false,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 1000 },
    stdout: 'ignore',
    stderr: 'ignore',
    env: {
      ...BACKEND_ENV,
      MKTKB_TRUSTED_ORIGINS: '["http://127.0.0.1:5300"]',
      MKTKB_TRACE_ENABLED: 'true',
    },
  },
  {
    command: 'node node_modules/vite/bin/vite.js preview --port 5300 --strictPort',
    cwd: HERE,
    url: 'http://127.0.0.1:5300',
    timeout: 120_000,
    reuseExistingServer: false,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 1000 },
    stdout: 'ignore',
    stderr: 'ignore',
    env: {
      T08_BACKEND_ORIGIN: 'http://127.0.0.1:8289',
    },
  },
];

const TRACE_OFF_STACK = [
  {
    command:
      '..\\.venv\\Scripts\\python.exe -B -m uvicorn mktkb.main:create_app --factory --host 127.0.0.1 --port 8292',
    cwd: path.join(PROJECT_ROOT, 'backend'),
    url: 'http://127.0.0.1:8292/api/v1/healthz',
    timeout: 180_000,
    reuseExistingServer: false,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 1000 },
    stdout: 'ignore',
    stderr: 'ignore',
    env: {
      ...BACKEND_ENV,
      MKTKB_TRUSTED_ORIGINS: '["http://127.0.0.1:5302"]',
      MKTKB_TRACE_ENABLED: 'false',
    },
  },
  {
    command: 'node node_modules/vite/bin/vite.js preview --port 5302 --strictPort',
    cwd: HERE,
    url: 'http://127.0.0.1:5302',
    timeout: 120_000,
    reuseExistingServer: false,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 1000 },
    stdout: 'ignore',
    stderr: 'ignore',
    env: {
      T08_BACKEND_ORIGIN: 'http://127.0.0.1:8292',
    },
  },
];

/**
 * 本机内存紧张时可用 T304_STACK 拆栈跑：
 *   T304_STACK=main     → 只启 8289 + 5300（Q1-Q6、Q8-Q10）
 *   T304_STACK=traceoff → 只启 8292 + 5302（Q7，spec 里用绝对地址）
 * 不设置时为双栈（一次跑完整套）。
 */
const STACK = process.env.T304_STACK ?? 'both';
const WEBSERVERS =
  STACK === 'main' ? MAIN_STACK : STACK === 'traceoff' ? TRACE_OFF_STACK : [...MAIN_STACK, ...TRACE_OFF_STACK];

export default defineConfig({
  testDir: path.join(HERE, 'e2e'),
  testMatch: /operations-qa.*\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 120_000,
  expect: { timeout: 10_000 },
  outputDir: path.join(EVIDENCE_ROOT, 'playwright-results'),
  reporter: [
    ['list'],
    ['json', { outputFile: path.join(ROUND_DIR, 'playwright-qa.json') }],
    ['html', { outputFolder: path.join(ROUND_DIR, 'playwright-report'), open: 'never' }],
  ],
  use: {
    baseURL: 'http://127.0.0.1:5300',
    locale: 'zh-CN',
    timezoneId: 'Asia/Shanghai',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'off',
    actionTimeout: 10_000,
    navigationTimeout: 20_000,
    launchOptions: {
      // 本机物理内存 16GB、系统提交额度紧张，Chromium 默认会在提交上限附近直接崩渲染进程
      // （表现为 page.goto net::ERR_ABORTED / VirtualAlloc failed）。以下参数压低单浏览器提交占用，
      // 不改变页面行为与被测逻辑。
      args: [
        '--disable-gpu',
        '--disable-software-rasterizer',
        '--disable-features=site-per-process',
        '--renderer-process-limit=1',
        '--js-flags=--max-old-space-size=384',
      ],
    },
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
  webServer: WEBSERVERS,
});
